"""Bind existing Builder/Run evidence to the exact requested candidate."""

from agent.duet_contracts import canonical_json
from function_library.epistemic_contract import exact
from function_library.refinement_contract import ROLE_SPECIALIZATION

from .checking import checker_definition
from .evaluation_inputs import native_launch
from .records import Ref
from .state_machine import actor, index, proposed


def _request(view, attempt, record):
    actor(view, attempt)
    request_ref = Ref.from_record(record.body["request_ref"])
    request = view.entry("evaluation", request_ref.artifact_id.value).record
    if (
        request.ref != request_ref
        or request.invocation_id != attempt.invocation_id
        or record.body["candidate_ref"] != request.body["candidate_ref"]
    ):
        raise ValueError(
            "validation binding differs from its requested candidate or owner"
        )
    if not request.body.get("availability", {"executable": True})["executable"]:
        raise ValueError(
            "unavailable evaluation cannot bind source or a validation Run"
        )
    return request


def _source_matches(view, record, resolved):
    if (
        resolved.references["expected_source_files"]
        != resolved.references["source_files"]
        or resolved.references["source_workflow"]
        != resolved.references["target_workflow"]
        or resolved.references["source_authority"]
        != resolved.references["expected_source_authority"]["artifact_id"]
    ):
        raise ValueError(
            "admitted source does not materialize this exact candidate under target authority"
        )


def record_source(view, attempt, resolved):
    exact(attempt.body["payload"], {"source"}, "source admission publication")
    source = proposed(view, attempt, "source", "evaluation_source")
    request = _request(view, attempt, source)
    _source_matches(view, source, resolved)
    admitted = resolved.references["build_receipt"]["status"] == "materialized"
    if type(source.body["admitted"]) is not bool or source.body["admitted"] != admitted:
        raise ValueError("source admission outcome differs from its Builder receipt")
    return [source], [
        index(
            "evaluation_source",
            request.artifact_id.value,
            source,
            "admitted" if admitted else "rejected",
        )
    ]


def bind_run(view, attempt, resolved):
    exact(attempt.body["payload"], {"binding"}, "validation Run binding")
    binding = proposed(view, attempt, "binding", "evaluation_run")
    request = _request(view, attempt, binding)
    source = view.entry("evaluation_source", request.artifact_id.value)
    if (
        source.status != "admitted"
        or source.record.body["build_receipt_ref"] != binding.body["build_receipt_ref"]
        or source.record.body["candidate_ref"] != binding.body["candidate_ref"]
    ):
        raise ValueError("validation requires this candidate's admitted source receipt")
    _source_matches(view, binding, resolved)
    if canonical_json(binding.body["registration"]) != canonical_json(
        resolved.references["admitted_registration"]
    ):
        raise ValueError(
            "validation registration differs from the actual admitted build"
        )
    launch = binding.body["registration"]["launch_request"]
    existing = next(
        (
            row
            for row in view.entries("evaluation_run")
            if row.key == request.artifact_id.value
        ),
        None,
    )
    checker = checker_definition(view, request.body)
    stage = binding.body.get("checking_gap") or (
        binding.body if "target_run_ref" in binding.body else None
    )
    if stage is not None:
        if (
            checker is None
            or existing is None
            or existing.record.ref.as_record() != stage["target_run_ref"]
            or "target_run_ref" in existing.record.body
            or "checking_gap" in existing.record.body
            or existing.record.body["candidate_ref"] != binding.body["candidate_ref"]
            or existing.record.body["build_receipt_ref"]
            != binding.body["build_receipt_ref"]
        ):
            raise ValueError(
                "checking Run must follow this request's exact candidate Run once"
            )
        if "checking_gap" in binding.body:
            if canonical_json(binding.body["checking_gap"]) != canonical_json(
                resolved.references["checking_gap"]
            ) or canonical_json(binding.body["registration"]) != canonical_json(
                existing.record.body["registration"]
            ):
                raise ValueError(
                    "checking gap must retain its exact Target Workflow Run and host-derived cause"
                )
            return [binding], [
                index(
                    "evaluation_run", request.artifact_id.value, binding, "unavailable"
                )
            ]
        expected_launch = resolved.references["expected_checker_launch"]
    else:
        if existing is not None:
            raise ValueError("evaluation request already has a bound Run")
        expected_launch = native_launch(
            view,
            request.body,
            resolved.references["root_request_payload_contract"],
            request_id=launch["request_id"],
        ).as_record()
    if canonical_json(launch) != canonical_json(expected_launch):
        raise ValueError("validation Run does not use its measure's exact launch input")
    if "experiment_ref" in binding.body:
        from episode_runtime.testing_harness.contracts import ExperimentSpec

        experiment = view.data(Ref.from_record(binding.body["experiment_ref"]))
        spec = ExperimentSpec.from_record(experiment["spec"]).as_record()
        target_binding = (
            view.read(Ref.from_record(binding.body["target_run_ref"]), "evaluation_run")
            if "target_run_ref" in binding.body
            else binding
        )
        if (
            canonical_json(experiment["registration"])
            != canonical_json(target_binding.body["registration"])
            or target_binding.body.get("experiment_ref")
            != binding.body["experiment_ref"]
            or spec["candidate_ref"] != binding.body["candidate_ref"]
            or spec["campaign_ref"] != view.contract.ref.as_record()
            or spec["environment_ref"] != view.contract.body["environment_ref"]
            or spec["scope"]["kind"] != "workflow"
            or spec["mode"] not in {"live_fresh", "live_saved"}
        ):
            raise ValueError(
                "experiment cannot establish this campaign's native live judgment"
            )
        for requirement in spec["requirements"]:
            check = view.read(Ref.from_record(requirement["requirement_ref"]), "check")
            if (
                check.artifact_id.value not in request.body["check_keys"]
                or request.body["measure_ref"] != requirement["measure_ref"]
            ):
                raise ValueError(
                    "experiment changes the requested checks or parent measures"
                )
    return [binding], [index("evaluation_run", request.artifact_id.value, binding)]


def source_decision(view, attempt):
    """Return unavailable evidence to its owner while retaining static verdicts."""
    assignment = view.entry("invocation", attempt.invocation_id.value).record
    family = ROLE_SPECIALIZATION[assignment.body["role"]]
    if family not in {"verify", "measure", "support", "question"}:
        return None
    for row in reversed(view.entries("evaluation_source")):
        if (
            row.status != "rejected"
            or row.record.invocation_id != attempt.invocation_id
            or row.record.logical_unit_id != attempt.logical_unit_id
        ):
            continue
        request = view.read(
            Ref.from_record(row.record.body["request_ref"]), "evaluation"
        )
        if any(
            view.entry("check", key).record.body["evidence_kind"] == "execution"
            for key in request.body["check_keys"]
        ):
            return row.record
        if family == "verify":
            # A missing module/plan requires repair by the owner, not repeated
            # verification of identical bytes. Only this request's blocked,
            # mandatory contribution checks require that handoff; unrelated
            # unfinished nodes must not prevent a resolved static judgment.
            for observation in view.entries("observation"):
                record = observation.record
                if (
                    record.body["request_ref"] != request.ref.as_record()
                    or record.body["outcome"] != "blocked"
                ):
                    continue
                check = view.entry("check", record.body["check_key"]).record
                if (
                    check.body["evidence_kind"] == "materialization"
                    and check.body["mandatory"]
                    and check.body["requirement_key"]
                    in assignment.body["contribution_requirement_keys"]
                ):
                    return row.record
    return None
