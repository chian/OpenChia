"""Bounded high-level views shared by humans and approved testing Episodes.

Queries use existing artifact indexes and maintained Run records. They never
reconstruct an audit, contact services, admit findings or choose an experiment.
"""

from dataclasses import replace
from typing import Literal

from pydantic import Field, model_validator

from agent.duet_contracts import canonical_json, digest_record
from agent.episode_contracts import OpaqueId

from .experiments import execution_attempts, read_record, read_reference, read_run_intent, record_id
from .runs import EvidenceReference, RecordModel


class HistoryQuery(RecordModel):
    kind: Literal["experiments", "executions", "refinement"] = Field(
        default="experiments",
        description="Executions includes ordinary, refinement and experimental Runs; local-host access only. Workers see their execution views inside owned experiments.",
    )
    experiment_id: str | None = Field(
        default=None,
        min_length=1,
        description="When set, page saved recordings (default) or retained measurement reports for this owned experiment.",
    )
    experiment_collection: Literal["recordings", "reports"] = "recordings"
    attempt_run_id: str | None = Field(
        default=None,
        min_length=1,
        description="Pin recordings to one physical attempt of the owned experiment; omitted selects its current attempt.",
    )
    run_id: str | None = Field(
        default=None,
        min_length=1,
        description="With kind=executions, page this Run's saved recordings instead of executions.",
    )
    campaign_id: str | None = None
    invocation_id: str | None = None
    refinement_collection: Literal["observations", "reports", "conflicts", "controls"] | None = None
    requirement_key: str | None = Field(
        default=None,
        min_length=1,
        description="With refinement observations or conflicts, narrow to an assigned requirement; never expands the host-bound scope.",
    )
    conflict_status: Literal["suspected", "decision_required", "resolved"] | None = (
        Field(
            default=None,
            description="Optional exact status filter for refinement conflicts; omitted means all retained incidents.",
        )
    )
    campaign_head_ref: EvidenceReference | None = None
    after: str | None = None
    limit: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def matching_selection(self):
        if self.run_id is not None and self.kind != "executions":
            raise ValueError("run_id requires execution history")
        if self.experiment_id is not None and self.kind != "experiments":
            raise ValueError("experiment_id requires experiment history")
        if self.experiment_collection != "recordings" and self.experiment_id is None:
            raise ValueError("report history requires an exact experiment_id")
        if self.attempt_run_id is not None and (
            self.experiment_id is None or self.experiment_collection != "recordings"
        ):
            raise ValueError("attempt_run_id selects recordings of an exact experiment")
        if self.kind == "refinement":
            if not self.campaign_id or not self.invocation_id:
                raise ValueError(
                    "refinement history requires campaign_id and invocation_id"
                )
            if (
                self.requirement_key is not None
                and self.refinement_collection == "reports"
            ):
                raise ValueError(
                    "requirement_key selects observations or conflicts, not complete reports"
                )
            if (
                self.conflict_status is not None
                and self.refinement_collection != "conflicts"
            ):
                raise ValueError("conflict_status requires refinement conflicts")
        elif any(
            value is not None
            for value in (
                self.campaign_id,
                self.invocation_id,
                self.refinement_collection,
                self.campaign_head_ref,
                self.requirement_key,
                self.conflict_status,
            )
        ):
            raise ValueError("campaign selection requires refinement history")
        return self


class InvocationOwner(RecordModel):
    """Host-supplied visibility, never a field in the worker's query payload."""

    run_id: str
    episode_id: str
    registration_hash: str


def _reference(row):
    return {key: row[key] for key in ("artifact_id", "content_hash")}


def _verified(row):
    if digest_record(row["record"]).value != row["content_hash"]:
        raise ValueError("history record differs from its committed content hash")
    return row["record"]


def experiment_record_owner(artifacts, spec):
    """Resolve record ownership after the caller has authorized this exact spec."""
    from episode_runtime.testing.contracts import ExperimentSpec

    request = ExperimentSpec.from_record(spec)
    row = read_record(artifacts, "dispatch", experiment_id=request.experiment_id)
    if row is None:
        row = read_record(artifacts, "numerical", experiment_id=request.experiment_id)
    if row is None:
        return None
    if canonical_json(row["record"]["spec"]) != canonical_json(request.as_record()):
        raise ValueError("experiment record differs from the authorized specification")
    return row["duet_id"]


def inventory(artifacts, runs, *, duet_id, source, query):
    from .inventory import InventoryRequest

    request = InventoryRequest.model_validate({"source": source, "query": query})
    selection = {}
    source_owner = duet_id
    expected_source_run_id = None
    if request.source.kind == "run":
        run_id = request.source.run_id
    else:
        reference = None
        if request.source.kind == "experiment":
            experiment_id = request.source.experiment_id
            dispatch = read_record(artifacts, "dispatch", experiment_id=experiment_id)
            if dispatch is not None:
                if dispatch["duet_id"] != duet_id:
                    raise ValueError("inventory experiment belongs to another owner")
                return _experiment_inventory(artifacts, runs, dispatch, request, duet_id)
            else:
                numerical = read_record(
                    artifacts, "numerical", experiment_id=experiment_id
                )
                if numerical is None or numerical["duet_id"] != duet_id:
                    raise ValueError(
                        "inventory experiment has no available execution or numerical recording"
                    )
                reference = numerical["record"]["spec"]["recording_ref"]
                expected_source_run_id = numerical["record"]["report"]["source_run_id"]
                source_owner = runs.read_registration(
                    OpaqueId(expected_source_run_id)
                ).duet_id.value
        else:
            reference = request.source.recording_ref.model_dump(mode="json")
        if reference is not None:
            row = read_reference(artifacts, reference, source_owner)
            if row["kind"] != "experiment.recording.v1":
                raise ValueError("inventory requires an exact saved recording selector")
            selector = row["record"]
            run_id = selector["registration_ref"]["run_id"]
            if expected_source_run_id is not None and run_id != expected_source_run_id:
                raise ValueError("numerical inventory selector belongs to another source Run")
            selection = {
                "selected_episode_ids": selector["selected_episode_ids"] or None,
                "through_event_ref": selector["through_event_ref"],
            }
            registration = runs.read_registration(OpaqueId(run_id))
            if (
                registration.registration_hash.value
                != selector["registration_ref"]["content_hash"]
            ):
                raise ValueError(
                    "inventory recording belongs to a different registration"
                )
    registration = runs.read_registration(OpaqueId(run_id))
    if registration.duet_id.value != source_owner:
        raise ValueError("inventory Run belongs to another owner")
    return {
        **runs.read_inventory(
            registration.run_id, request.query.model_dump(mode="json"), **selection
        ),
        "source": request.source.model_dump(mode="json"),
    }


def _experiment_inventory(artifacts, runs, dispatch, request, duet_id):
    from episode_runtime.contracts import RunRegistration

    original = dispatch["record"]["registration"]
    attempts = execution_attempts(artifacts, None, original["run_id"]) or (dispatch,)
    source = request.source.model_dump(mode="json")
    choices = []
    for attempt in attempts:
        registration = attempt["record"]["registration"]
        if registration["duet_id"] != duet_id:
            intent = read_run_intent(
                artifacts,
                {"artifact_id": dispatch["artifact_id"], "content_hash": dispatch["content_hash"]},
                RunRegistration.from_record(registration),
            )
            if intent["duet_id"] != duet_id:
                raise ValueError("inventory Run belongs to another owner")
        view = _run_view(runs, registration)
        record = view["record"]
        position = None if record is None else record["through_event"]
        prefix = None if position is None else {
            "run_id": registration["run_id"],
            "event_id": position["event_id"], "content_hash": position["content_hash"],
        }
        usable = prefix is not None and view["index_status"] in {"current", "publication_pending"}
        choices.append({
            "run_id": registration["run_id"],
            "registration_hash": registration["registration_hash"],
            "index_status": view["index_status"],
            "required_action": view.get("required_action"),
            "through_event_ref": prefix,
            "inventory_requests": None if not usable else {
                kind: {
                    "source": source,
                    "query": {
                        **request.query.model_dump(mode="json"),
                        "kind": kind, "through_event_ref": prefix, "after": None,
                    },
                }
                for kind in ("invocations", "units")
            },
        })
    context = {
        "source": source,
        "coverage": "physical_attempt_only",
        "logical_run_id": original["run_id"],
        "current_run_id": choices[-1]["run_id"],
        "attempts": choices,
    }
    limitations = [
        "Each inventory covers only one physical attempt at its exact prefix; inherited starts are not copied into later attempts.",
        "An absent completion and local counts do not describe the logical invocation's current state. Inspect later attempts using the same episode_id to find newly completed units.",
    ]
    prefix = request.query.through_event_ref
    if len(choices) > 1 and prefix is None:
        return {
            **context,
            "schema_version": 1, "kind": request.query.kind,
            "selection_status": "required", "index_status": "not_selected",
            "required_action": "select_attempt_prefix",
            "run_id": None, "registration_hash": None, "through_event_ref": None,
            "items": [], "next_query": None, "limitations": limitations,
        }
    selected = original["run_id"] if prefix is None else prefix.run_id
    if not any(choice["run_id"] == selected for choice in choices):
        raise ValueError("inventory prefix is outside the owned experiment lineage")
    page = runs.read_inventory(OpaqueId(selected), request.query.model_dump(mode="json"))
    return {
        **page, **context, "selection_status": "selected",
        "limitations": [*page["limitations"], *limitations],
    }


def recording_choices(artifacts, runs, duet_id, run_id, *, query):
    page = artifacts.artifact_page(
        duet_id=duet_id,
        kinds=("experiment.recording.v1",),
        recording_run_id=run_id,
        limit=query.limit,
        after=query.after,
    )
    return {
        "query": query.model_dump(mode="json"),
        "items": [
            recording_choice(row, artifacts=artifacts, runs=runs)
            for row in page["items"]
        ],
        "next_cursor": page["next_cursor"],
        "next_query": None
        if page["next_cursor"] is None
        else {
            **query.model_dump(mode="json"),
            "after": page["next_cursor"],
        },
    }


def recording_choice(row, *, artifacts, runs):
    from episode_runtime.store import RunStoreNotFound

    if row["kind"] != "experiment.recording.v1":
        raise ValueError("recording history requires a saved recording selector")
    selector = _verified(row)
    source = {"kind": "recording", "recording_ref": _reference(row)}
    request = {"source": source, "query": {"kind": "invocations", "limit": 3}}
    try:
        selected = inventory(artifacts, runs, duet_id=row["duet_id"], **request)
    except RunStoreNotFound:
        selected = {
            "index_status": "unavailable",
            "items": [],
            "next_query": None,
            "required_action": "restore_source_run",
            "limitations": [
                "The saved selector is retained, but its source Run is unavailable in this RunStore."
            ],
        }
    execution = read_record(
        artifacts, "execution", run_id=selector["registration_ref"]["run_id"]
    )
    context_available = (
        execution is not None and execution["record"].get("context") is not None
    )
    return {
        "recording_ref": _reference(row),
        "registration_ref": selector["registration_ref"],
        "through_event_ref": selector["through_event_ref"],
        "selected_episode_count": len(selector["selected_episode_ids"]),
        "selection": "listed_invocations"
        if selector["selected_episode_ids"]
        else "all_invocations_at_prefix",
        "invocations": selected,
        "inventory_request": request,
        "next_inventory_request": None
        if selected["next_query"] is None
        else {
            "source": source,
            "query": selected["next_query"],
        },
        "reuse": {
            "saved_inputs": "requires_boundary_validation",
            "recorded_responses": "requires_preview"
            if context_available
            else "missing_execution_context",
            "numerical": "inspect_admitted_observations",
            "continue_interrupted": "not_a_continuation_boundary",
        },
        "limitations": [
            "Only this exact selector is available; a source Run may contain unrelated invocations or later evidence.",
            "Response counts do not prove usable content or matching requests. Preview the complete experiment before reuse.",
            "A saved invocation/prefix selector does not authorize whole-Run continuation; inspect the owned experiment's current execution boundary.",
        ],
    }


def _measurement(artifacts, experiment_id):
    from episode_runtime.testing.measurements import saved_measurements

    value = saved_measurements(artifacts, experiment_id)
    if value is None:
        return {"candidate_verdict": "unmeasured", "outcomes": []}
    return {
        "candidate_verdict": value["candidate_verdict"],
        "measurement_ref": value["measurement_ref"],
        "execution_ref": value["execution_ref"],
        "outcomes": value["outcomes"],
        "limitations": value["limitations"],
        "unresolved_questions": value["unresolved_questions"],
    }


def _run_view(runs, registration):
    from episode_runtime.store import RunStoreNotFound

    try:
        view = runs.read_run_record(OpaqueId(registration["run_id"]))
    except RunStoreNotFound:
        view = {"index_status": "unavailable", "record": None}
    record = view["record"]
    if (
        record is not None
        and record["registration_hash"] != registration["registration_hash"]
    ):
        raise ValueError("history Run record belongs to a different execution")
    return view


def _attempt_summary(artifacts, runs, row, *, experiment_id):
    registration = row["record"]["registration"]
    view = _run_view(runs, registration)
    record = view["record"]
    return {
        "run_id": registration["run_id"],
        "registration_hash": registration["registration_hash"],
        "execution_ref": _reference(row),
        "index_status": view["index_status"],
        "execution_status": "registration_unavailable" if record is None
        else record["terminal_status"] or "no_terminal_event",
        "evidence_ref": None if record is None else record["evidence_ref"],
        "recordings_query": _recordings_query(registration["run_id"], experiment_id).model_dump(mode="json"),
        "refinement": _refinement_result(artifacts, registration, experiment_id),
    }


def _recordings_query(run_id, experiment_id):
    return (
        HistoryQuery(experiment_id=experiment_id, attempt_run_id=run_id)
        if experiment_id is not None
        else HistoryQuery(kind="executions", run_id=run_id)
    )


def _refinement_result(artifacts, registration, experiment_id):
    if experiment_id is None:
        return None
    continued = registration.get("resume_from") is not None
    row = read_record(
        artifacts, "refinement_result_attempt" if continued else "refinement_result",
        experiment_id=experiment_id,
        **({"run_id": registration["run_id"]} if continued else {}),
    )
    if row is None:
        return None
    dispatch = read_record(artifacts, "dispatch", experiment_id=experiment_id)
    if dispatch is None or row["duet_id"] != dispatch["duet_id"]:
        raise ValueError("refinement result belongs to another experiment owner")
    return {
        "result_ref": _reference(row),
        **{key: row["record"][key] for key in (
            "campaign_ref", "disposition", "build_status", "verification_gaps",
        )},
    }


def _continuation(view, *, mode, current, experiment_id):
    record = view["record"]
    reference = None
    if not current:
        availability = "already_continued"
    elif view["index_status"] != "current" or record is None:
        availability = "requires_current_terminal_record"
    elif record["terminal_status"] not in {"interrupted", "cancelled", "resource_limited"}:
        availability = "not_interrupted"
    elif record["evidence_ref"] is None or record["through_event"] is None:
        availability = "terminal_evidence_unavailable"
    else:
        reference = {
            "run_id": record["run_id"],
            "registration_hash": record["registration_hash"],
            "terminal_event_id": record["through_event"]["event_id"],
            "terminal_event_hash": record["through_event"]["content_hash"],
        }
        availability = (
            "recorded_mode_unsupported" if mode not in {"live_fresh", "live_saved"}
            else "requires_owned_experiment" if experiment_id is None
            else "requires_validation"
        )
    return {
        "availability": availability,
        "resume_from": reference,
        "request": {
            "operation": "continue", "payload": {"experiment_id": experiment_id, "resume_from": reference},
        } if availability == "requires_validation" else None,
        "limitations": [
            "The reference identifies recorded interruption, not a resumable checkpoint or launch permission.",
            "The service must verify stopped execution, supported source, exact history, restored host state and current authority before new work.",
        ],
    }


def execution_overview(artifacts, runs, row, *, experiment_id=None):
    binding = _verified(row)
    registration = binding["registration"]
    run_id, duet_id = registration["run_id"], registration["duet_id"]
    if row["duet_id"] != duet_id or row["artifact_id"] != record_id(
        "execution", run_id=run_id
    ):
        raise ValueError("history execution belongs to a different owner")
    attempts = execution_attempts(artifacts, None, run_id)
    if not attempts:
        raise ValueError("history execution has no committed dispatch")
    current = attempts[-1]["record"]["registration"]["run_id"] == run_id
    view = _run_view(runs, registration)
    record = view["record"]
    choices = recording_choices(
        artifacts,
        runs,
        duet_id,
        run_id,
        query=_recordings_query(run_id, experiment_id),
    )
    context = binding.get("context")
    intent = _execution_intent(artifacts, duet_id, binding)
    measured_experiment = intent.get("experiment_id")
    measurement = (
        None
        if measured_experiment is None
        else _measurement(artifacts, measured_experiment)
    )
    if measurement is not None and (
        record is None or measurement.get("execution_ref") != record["evidence_ref"]
    ):
        measurement = None
    continuation = _continuation(
        view, mode=binding["mode"], current=current,
        experiment_id=measured_experiment or intent.get("parent_experiment_id"),
    )
    return {
        "execution_ref": _reference(row),
        "run_id": run_id,
        "logical_run_id": attempts[0]["record"]["registration"]["run_id"],
        "is_current_attempt": current,
        "current_execution_ref": _reference(attempts[-1]),
        "attempts": [
            _attempt_summary(artifacts, runs, attempt, experiment_id=experiment_id)
            for attempt in attempts
        ],
        "build_receipt_id": registration["build_receipt_id"],
        "intent_ref": binding["intent_ref"],
        "intent": intent,
        "mode": binding["mode"],
        "scope": _scope_overview(binding["scope"]),
        "run_record": view,
        "execution_status": "registration_unavailable"
        if record is None
        else record["terminal_status"] or "no_terminal_event",
        "candidate_verdict": "unmeasured"
        if measurement is None
        else measurement["candidate_verdict"],
        "measurement_ref": None
        if measurement is None
        else measurement.get("measurement_ref"),
        "recordings": choices,
        "continuation": continuation,
        "reuse": {
            "saved_inputs": "requires_preview",
            "recorded_responses": "missing_execution_context"
            if context is None
            else "requires_preview"
            if choices["items"]
            else "save_recording_first",
            "numerical": "requires_preview"
            if record is not None and record["activity"]["learning_commits"]
            else "no_indexed_observations",
            "continue_interrupted": continuation["availability"],
        },
        "limitations": [
            "Execution status is not process liveness, requirement acceptance or refinement credit. Non-experimental measurement remains with the linked judgment contract.",
            "Reuse choices are inspection leads, not authorization or guarantees of compatible responses.",
            "Use inventory to inspect exact invocations, then preview the complete next experiment.",
        ],
    }


def _scope_overview(scope):
    result = {
        key: scope[key]
        for key in ("kind", "entry_local_id", "included_local_ids")
    }
    boundary = scope.get("boundary", {})
    if boundary.get("origin") == "fresh_typed_entry":
        result.update(
            boundary_origin=boundary["origin"],
            boundary_ref=scope["boundary_ref"],
            limitations=boundary["limitations"],
        )
    return result


def _execution_intent(artifacts, duet_id, binding):
    """Project fixed provenance fields, never arbitrary intent prose or results."""
    from episode_runtime.contracts import RunRegistration

    row = read_run_intent(
        artifacts,
        binding["intent_ref"],
        RunRegistration.from_record(binding["registration"]),
    )
    projector = {
        "experiment.dispatch.v1": _experiment_intent,
        "experiment.instrument.v1": _instrument_intent,
        "experiment.launch_intent.v1": _launch_intent,
        "refinement.campaign.v1": _refinement_intent,
        "refinement.evaluation_run.v1": _refinement_intent,
        "refinement.measure_control_run.v1": _refinement_intent,
    }.get(row["kind"])
    return {
        "kind": row["kind"],
        **({"relationship": "other"} if projector is None else projector(artifacts, row, binding)),
    }


def _experiment_intent(artifacts, row, binding):
    from episode_runtime.testing.contracts import ExperimentSpec

    subject = row["record"]["plan"].get("subject")
    detail = _subject_summary(subject)
    return {
        "relationship": detail.pop("kind") if detail else "experiment",
        "experiment_id": ExperimentSpec.from_record(row["record"]["spec"]).experiment_id,
        **detail,
    }


def _subject_summary(subject):
    if subject is None:
        return {}
    names = {
        "grounded_control": ("measure_adequacy_control", "control_target_ref"),
        "refinement_job": ("refinement_job", "campaign_ref"),
        "campaign_evaluation": ("campaign_evaluation", "campaign_ref"),
    }
    kind, reference_key = names[subject["kind"]]
    return {
        "kind": kind, reference_key: subject["reference"],
        **({"source_kind": subject["source_kind"], "source_owner_duet_id": subject["source_owner_duet_id"]}
           if subject["kind"] == "campaign_evaluation" else {}),
    }


def _instrument_intent(artifacts, row, binding):
    from episode_runtime.testing.contracts import ExperimentSpec
    from episode_runtime.contracts import RunRegistration

    value = row["record"]
    parent = read_reference(artifacts, value["experiment_ref"], row["duet_id"])
    if parent["kind"] != "experiment.dispatch.v1":
        raise ValueError("measurement Run requires its frozen parent experiment")
    experiment_id = ExperimentSpec.from_record(parent["record"]["spec"]).experiment_id
    declared = any(
        item.get("eligible")
        and item.get("instrument") is not None
        and item["instrument"]["instrument_id"] == value["instrument_id"]
        for item in parent["record"]["plan"]["measurements"]
    )
    if (
        not declared
        or row["artifact_id"] != record_id(
            "instrument", experiment_id=experiment_id, instrument_id=value["instrument_id"]
        )
        or canonical_json(value["registration"]) != canonical_json(
            replace(RunRegistration.from_record(binding["registration"]), resume_from=None).as_record()
        )
    ):
        raise ValueError("measurement Run differs from its declared instrument")
    # This Run supplies evidence to its parent experiment. The parent's target
    # verdict is not a requirement verdict about the checker implementation.
    return {
        "relationship": "experiment_instrument",
        "instrument_id": value["instrument_id"],
        "experiment_ref": value["experiment_ref"],
        "parent_experiment_id": experiment_id,
        "target_execution_ref": value["target_execution_ref"],
    }


def _launch_intent(artifacts, row, binding):
    return {
        "relationship": "ordinary_run",
        **{key: row["record"][key] for key in ("model_launch_id", "configuration_hash")},
    }


def _refinement_intent(artifacts, row, binding):
    from iterative_episode_refiner.records import RefinementRecord

    value = row["record"]
    record = RefinementRecord.from_record(value)
    if row["kind"] != f"refinement.{record.kind}.v1":
        raise ValueError("execution intent has a different refinement record kind")
    # A schema name in ordinary data is not campaign provenance. These
    # exact typed intent records link Runs without scanning campaign history.
    result = {
        "relationship": "refinement",
        **{
            key: value[key]
            for key in ("campaign_id", "invocation_id", "logical_unit_id")
        },
    }
    body = value["body"]
    result.update({
        key: body[key]
        for key in (
            "candidate_ref",
            "request_ref",
            "proposal_ref",
            "grounding_ref",
            "control_ref",
            "target_run_ref",
            "target_execution_ref",
            "checking_gap",
        )
        if key in body
    })
    if row["kind"] == "refinement.evaluation_run.v1":
        request = read_reference(artifacts, body["request_ref"], row["duet_id"])
        if (
            request["kind"] != "refinement.evaluation.v1"
            or request["record"]["campaign_id"] != value["campaign_id"]
        ):
            raise ValueError("execution request belongs to another refinement campaign")
        result.update({
            key: request["record"]["body"][key]
            for key in (
                "purpose",
                "check_keys",
                "measure_ref",
                "environment_ref",
            )
        })
    return result


def experiment_overview(artifacts, runs, spec):
    from episode_runtime.testing.contracts import ExperimentSpec

    request = ExperimentSpec.from_record(spec)
    result = {
        "experiment_id": request.experiment_id,
        **{
            key: spec[key]
            for key in (
                "question",
                "rationale",
                "candidate_ref",
                "build_receipt_ref",
                "environment_ref",
                "scope",
                "mode",
                "requirements",
                "unresolved_questions",
            )
        },
        "measurement": _measurement(artifacts, request.experiment_id),
        "reports_query": {
            "kind": "experiments", "experiment_id": request.experiment_id,
            "experiment_collection": "reports",
        },
    }
    dispatch = read_record(artifacts, "dispatch", experiment_id=request.experiment_id)
    if dispatch is not None:
        subject = dispatch["record"]["plan"].get("subject")
        if subject is not None:
            result["subject"] = _subject_summary(subject)
        run_id = dispatch["record"]["registration"]["run_id"]
        attempts = execution_attempts(artifacts, None, run_id)
        execution = attempts[-1] if attempts else None
        result["execution"] = (
            None
            if execution is None
            else execution_overview(
                artifacts,
                runs,
                execution,
                experiment_id=request.experiment_id,
            )
        )
    else:
        result["execution"] = None
    numerical = read_record(artifacts, "numerical", experiment_id=request.experiment_id)
    if numerical is not None:
        value = numerical["record"]["report"]
        result["numerical"] = {
            "result_ref": _reference(numerical),
            **{
                key: value[key]
                for key in (
                    "execution_status",
                    "controller_comparison",
                    "recording_ref",
                    "source_run_id",
                    "limitations",
                )
            },
        }
    return result


def _history_spec(row, owner):
    from episode_runtime.testing.contracts import ExperimentSpec

    value = _verified(row)
    spec = ExperimentSpec.from_record(value["spec"])
    if owner is not None and (
        value["registration_hash"] != owner.registration_hash
        or value["episode_id"] != owner.episode_id
        or row["artifact_id"]
        != record_id(
            "access",
            run_id=owner.run_id,
            episode_id=owner.episode_id,
            key=spec.experiment_id,
        )
    ):
        raise ValueError("history access record differs from its invocation owner")
    return spec


def _owned_experiment(artifacts, *, duet_id, query, owner):
    if owner is None:
        row = read_record(artifacts, "dispatch", experiment_id=query.experiment_id)
        if row is None:
            row = read_record(artifacts, "numerical", experiment_id=query.experiment_id)
    else:
        row = read_record(
            artifacts,
            "access",
            run_id=owner.run_id,
            episode_id=owner.episode_id,
            key=query.experiment_id,
        )
    if row is None or row["duet_id"] != duet_id:
        raise ValueError("experiment is not available to this history owner")
    if _history_spec(row, owner).experiment_id != query.experiment_id:
        raise ValueError("history record differs from the requested experiment")
    return row


def _experiment_recordings(artifacts, runs, *, duet_id, query, owner):
    _owned_experiment(artifacts, duet_id=duet_id, query=query, owner=owner)
    dispatch = read_record(artifacts, "dispatch", experiment_id=query.experiment_id)
    if dispatch is None:
        return {
            "query": query.model_dump(mode="json"),
            "items": [],
            "next_cursor": None,
            "next_query": None,
            "unavailable_reason": "Experiment has no dispatched Run; source recordings remain exact input references, not access to the source Run's other recordings.",
        }
    attempts = execution_attempts(artifacts, None, dispatch["record"]["registration"]["run_id"])
    if not attempts:
        return {
            "query": query.model_dump(mode="json"), "items": [],
            "next_cursor": None, "next_query": None,
            "unavailable_reason": "Experiment intent has no committed execution dispatch.",
        }
    selected = query.attempt_run_id or attempts[-1]["record"]["registration"]["run_id"]
    attempt = next(
        (row for row in attempts if row["record"]["registration"]["run_id"] == selected),
        None,
    )
    if attempt is None:
        raise ValueError("recording attempt is outside the owned experiment lineage")
    registration = attempt["record"]["registration"]
    return recording_choices(
        artifacts,
        runs,
        registration["duet_id"],
        registration["run_id"],
        query=query.model_copy(update={"attempt_run_id": selected}),
    )


def _experiment_reports(artifacts, *, duet_id, query, owner):
    from .outcomes import RequirementOutcome

    owned = _owned_experiment(artifacts, duet_id=duet_id, query=query, owner=owner)
    record_owner = experiment_record_owner(artifacts, owned["record"]["spec"])
    current_ref = _measurement(artifacts, query.experiment_id).get("measurement_ref")
    page = {"items": [], "next_cursor": None} if record_owner is None else artifacts.artifact_page(
        duet_id=record_owner,
        kinds=("experiment.measurement.v1", "experiment.measurement_attempt.v1"),
        experiment_id=query.experiment_id, limit=query.limit, after=query.after,
    )
    items = []
    for row in page["items"]:
        value = _verified(row)
        items.append({
            "measurement_ref": _reference(row),
            "is_current": _reference(row) == current_ref,
            "execution_ref": value["execution_ref"],
            "candidate_verdict": value["candidate_verdict"],
            "outcomes": [RequirementOutcome.model_validate(outcome).model_dump(mode="json") for outcome in value["outcomes"]],
            "limitations": value["limitations"],
            "unresolved_questions": value["unresolved_questions"],
        })
    return {
        "query": query.model_dump(mode="json"),
        "current_measurement_ref": current_ref,
        "items": items,
        "next_cursor": page["next_cursor"],
        "next_query": None if page["next_cursor"] is None else {
            **query.model_dump(mode="json"), "after": page["next_cursor"],
        },
    }


def history(artifacts, runs, *, duet_id, query, invocation=None):
    query = HistoryQuery.model_validate(query)
    owner = None if invocation is None else InvocationOwner.model_validate(invocation)
    if query.kind == "refinement":
        if owner is not None:
            raise ValueError(
                "refinement history requires the host-bound refinement assignment, not a worker-selected invocation"
            )
        from .refinement import refinement_history

        return refinement_history(artifacts, duet_id=duet_id, query=query)
    result = {
        "schema_version": 1,
        "assigned_recordings": [],
        "limitations": [
            "History is restricted to the selected owner; it does not grant access to unrelated sibling histories.",
            "Recorded evidence is not a coherent nested checkpoint. Preview is required before reuse.",
        ],
    }
    if query.kind == "executions":
        if owner is not None:
            raise ValueError(
                "workers inspect execution views through owned experiments, not Duet-wide execution history"
            )
        if query.run_id is not None:
            row = read_record(artifacts, "execution", run_id=query.run_id)
            if row is None or row["duet_id"] != duet_id:
                raise ValueError("execution is not available to this history owner")
            return {
                **result,
                "record_type": "recordings",
                "run_id": query.run_id,
                **recording_choices(
                    artifacts, runs, duet_id, query.run_id, query=query
                ),
            }
        page = artifacts.artifact_page(
            duet_id=duet_id,
            kinds=("experiment.execution.v1",),
            limit=query.limit,
            after=query.after,
        )
        return {
            **result,
            "record_type": "executions",
            "query": query.model_dump(mode="json"),
            "next_cursor": page["next_cursor"],
            "next_query": None
            if page["next_cursor"] is None
            else {
                **query.model_dump(mode="json"),
                "after": page["next_cursor"],
            },
            "items": [
                execution_overview(artifacts, runs, row) for row in page["items"]
            ],
        }
    if query.experiment_id is not None:
        if query.experiment_collection == "reports":
            return {
                **result, "record_type": "reports", "experiment_id": query.experiment_id,
                **_experiment_reports(artifacts, duet_id=duet_id, query=query, owner=owner),
            }
        return {
            **result,
            "record_type": "recordings",
            "experiment_id": query.experiment_id,
            **_experiment_recordings(
                artifacts, runs, duet_id=duet_id, query=query, owner=owner
            ),
        }
    page = artifacts.artifact_page(
        duet_id=duet_id,
        kinds=("experiment.dispatch.v1", "experiment.numerical.v1")
        if owner is None
        else ("experiment.access.v1",),
        episode_id=None if owner is None else owner.episode_id,
        limit=query.limit,
        after=query.after,
    )
    return {
        **result,
        "record_type": "experiments",
        "query": query.model_dump(mode="json"),
        "next_cursor": page["next_cursor"],
        "next_query": None
        if page["next_cursor"] is None
        else {
            **query.model_dump(mode="json"),
            "after": page["next_cursor"],
        },
        "items": [
            experiment_overview(artifacts, runs, _history_spec(row, owner).as_record())
            for row in page["items"]
        ],
    }
