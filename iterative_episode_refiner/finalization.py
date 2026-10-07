"""Publish exact build evidence after the explicit refiner Run has returned.

This uses the existing artifact transaction, Builder receipts and Run evidence.
It creates no validation Run and approves no workflow or production launch.
"""

from dataclasses import replace

from agent.duet_contracts import canonical_json, digest_record
from agent.duet_store import DuetConflictError
from episode_builder._contract_base import BuildReceipt
from episode_builder.inspection import MaterializedSpecification
from episode_runtime.contracts import RunTerminalStatus

from .checking import (
    admitted_build,
    checker_definition,
    reference_definition,
    target_result,
)
from .grounding import authorize_acquisitions
from .measure_controls import confirm_control_evidence, final_control_rows
from .outcome import project_result
from .readiness import root_readiness
from .records import Ref, RefinementRecord


def _source_build(session, receipt_record):
    receipt = BuildReceipt.from_record(receipt_record)
    inputs = session.store.evidence.builds.inspection_inputs_for_receipt(
        receipt.receipt_id
    )
    frozen = session.store.evidence.reference(
        Ref.from_record(session.contract.body["target_workflow_ref"]), session.duet_id
    )
    if (
        inputs.receipt != receipt
        or not receipt.materialized
        or canonical_json(inputs.build_request.frozen_workflow.as_record())
        != canonical_json(frozen)
        or inputs.build_request.authority_approval.approval_id.value
        != session.contract.body["target_approval_ref"]["artifact_id"]
    ):
        raise ValueError("final source build differs from the exact approved candidate")
    session.store.evidence.builds.verify_source_package(inputs.manifest)
    handoff = session.store.evidence.materialization_handoff(receipt, session.duet_id)
    specification = MaterializedSpecification.from_record(
        handoff["materialized_specification"]
    )
    return inputs.manifest, specification


def _confirm_observations(session, evidence_rows):
    """Confirm admission provenance; judgment stays in the shared evaluator."""
    executions = {}
    reader = session.store.evidence
    for (
        check,
        observation,
        attempt,
        binding,
        source,
        target_binding,
        checker,
        reference_source,
    ) in evidence_rows:
        if (
            attempt.evidence_refs != observation.evidence_refs
            or attempt.body["payload"]["check_key"] != check.artifact_id.value
            or attempt.body["payload"]["request_ref"] != observation.body["request_ref"]
        ):
            raise ValueError("final observation differs from its audited attempt")
        if check.body["evidence_kind"] == "checking_program":
            from .authored_checks import verified_observation

            if attempt.body["action"] != "observe_checker":
                raise ValueError("final checking observation lacks its instrument execution")
            resolved = reader.resolve_attempt(attempt)
            with session.view() as view:
                _, _, _, checked, outcome = verified_observation(view, attempt, resolved)
            if (outcome != observation.body["outcome"]
                    or canonical_json(checked["result"]) != canonical_json(observation.body["observed_value"])):
                raise ValueError("final checking result differs from its saved execution")
        elif check.body["evidence_kind"] == "execution":
            execution_ref = Ref.from_record(observation.body["execution_ref"])
            reference = observation.evidence_refs[0]
            execution = reader.runs.read_evidence(reference.owner_id)
            if (
                attempt.body["action"] != "observe"
                or reference.store_kind != "run_audit"
                or execution.terminal_status is not RunTerminalStatus.SUCCEEDED
                or Ref(execution.evidence_id, execution.content_hash) != execution_ref
                or reference.record_id != execution.terminal_event_id
                or reference.observation_path != check.body["observation_path"]
                or canonical_json(
                    reader.runs.read_registration(execution.run_id).as_record()
                )
                != canonical_json(binding.body["registration"])
                or len(observation.evidence_refs) != 1
            ):
                raise ValueError(
                    "final acceptance lacks its bound successful validation Run"
                )
            observed = reader.read(
                reference,
                duet_id=session.duet_id,
                allowed_runs={execution.run_id.value},
            )
            if canonical_json(observed) != canonical_json(
                observation.body["observed_value"]
            ):
                raise ValueError(
                    "final observation differs from its committed Run event"
                )
            executions[execution.evidence_id.value] = Ref(
                execution.evidence_id, execution.content_hash
            ).as_record()
            if reference_source is not None:
                inputs = admitted_build(
                    reader, reference_source, duet_id=session.duet_id
                )
                if binding.body["registration"][
                    "build_receipt_id"
                ] != inputs.receipt.receipt_id.value or canonical_json(
                    reader.reference(
                        Ref.from_record(source.body["build_receipt_ref"]),
                        session.duet_id,
                    )
                ) != canonical_json(inputs.receipt.as_record()):
                    raise ValueError(
                        "grounding evidence belongs to another independent source build"
                    )
            if checker is not None:
                if (
                    target_binding is None
                    or target_binding.ref.as_record()
                    != binding.body.get("target_run_ref")
                    or any(
                        target_binding.body[field] != binding.body[field]
                        for field in (
                            "request_ref",
                            "candidate_ref",
                            "build_receipt_ref",
                        )
                    )
                ):
                    raise ValueError(
                        "independent acceptance lost its original candidate Run"
                    )
                inputs = admitted_build(reader, checker, duet_id=session.duet_id)
                if execution.run_id.value != binding.body["registration"]["run_id"] or (
                    binding.body["registration"]["build_receipt_id"]
                    != inputs.receipt.receipt_id.value
                ):
                    raise ValueError(
                        "final checker evidence belongs to another source build"
                    )
                _, target_evidence = target_result(
                    reader,
                    target_binding,
                    Ref.from_record(binding.body["target_execution_ref"]),
                )
                executions[target_evidence.evidence_id.value] = Ref(
                    target_evidence.evidence_id, target_evidence.content_hash
                ).as_record()
        else:
            if attempt.body["action"] != "observe_materialization":
                raise ValueError(
                    "final static acceptance lacks its Builder observation"
                )
            reference = observation.evidence_refs[0]
            if (
                len(observation.evidence_refs) != 1
                or reference.store_kind != "duet_artifact"
                or reference.observation_path != ""
                or Ref(reference.record_id, reference.content_hash).as_record()
                != source.body["build_receipt_ref"]
                or observation.body["execution_ref"] != source.ref.as_record()
            ):
                raise ValueError(
                    "final static observation lacks its exact admitted source receipt"
                )
            receipt = BuildReceipt.from_record(
                reader.read(reference, duet_id=session.duet_id, allowed_runs=set())
            )
            if reader.builds.read_receipt(receipt.receipt_id) != receipt:
                raise ValueError(
                    "final static evidence differs from the Builder receipt"
                )
    return [executions[key] for key in sorted(executions)]


def _observation_rows(view, observations):
    """Acceptance and acquired grounding retain the same original Run bindings."""
    evidence_rows, run_bindings = [], {}
    for observation in observations:
        check = view.read(observation.body["check_key"], "check")
        attempt = view.read(observation.predecessor_refs[0], "attempt")
        binding, target_binding, checker, reference_source = None, None, None, None
        request_key = observation.body["request_ref"]["artifact_id"]
        if check.body["evidence_kind"] == "execution":
            binding = view.entry("evaluation_run", request_key).record
            run_bindings[binding.artifact_id.value] = binding
            request = view.read(
                Ref.from_record(observation.body["request_ref"]), "evaluation"
            )
            checker = checker_definition(view, request.body)
            reference_source = reference_definition(
                view.data, view.contract, request.body
            )
            if "target_run_ref" in binding.body:
                target_binding = view.read(
                    Ref.from_record(binding.body["target_run_ref"]), "evaluation_run"
                )
                run_bindings[target_binding.artifact_id.value] = target_binding
        observed_source = (None if check.body["evidence_kind"] == "checking_program"
                           else view.entry("evaluation_source", request_key).record)
        evidence_rows.append((
            check,
            observation,
            attempt,
            binding,
            observed_source,
            target_binding,
            checker,
            reference_source,
        ))
    return evidence_rows, run_bindings


def finalize_result(session, evidence):
    result = project_result(session, evidence)
    with session.view() as view:
        assignment = view.read(
            Ref.from_record(result.root_report.body["assignment_ref"]), "assignment"
        )
        readiness = root_readiness(view, assignment, session.policy)
        gaps = list(readiness["gaps"])
        if not result.has_terminal_report or result.disposition != "attained":
            gaps.insert(
                0,
                {
                    "code": "root_not_attained",
                    "requirement_keys": readiness["mandatory_requirement_keys"],
                    "record_refs": [],
                },
            )
        if gaps:
            return replace(result, verification_gaps=tuple(gaps))
        if result.candidate.ref != view.candidate.ref:
            raise DuetConflictError("candidate changed after the root return")
        units = [
            row.record
            for row in view.entries("unit")
            if row.record.invocation_id == result.root_report.invocation_id
        ]
        unit = units[-1]
        continuation = view.read(
            Ref.from_record(unit.body["continuation_ref"]), "continuation"
        )
        if (
            unit.body["disposition"] != "attained"
            or not continuation.body["attained"]
            or not continuation.body["stop"]
            or unit.body["candidate_after_ref"] != result.candidate.ref.as_record()
            or result.root_report.body["continuation_ref"]
            != continuation.ref.as_record()
        ):
            raise ValueError(
                "verified build requires the root's exact attained numerical return"
            )
        source = view.read(
            Ref.from_record(readiness["source_admission_ref"]), "evaluation_source"
        )
        receipt_record = view.data(Ref.from_record(source.body["build_receipt_ref"]))
        checks = [
            view.read(Ref.from_record(ref), "check") for ref in readiness["check_refs"]
        ]
        observations = [
            view.read(Ref.from_record(ref), "observation")
            for ref in readiness["observation_refs"]
        ]
        measure_refs = list(
            {
                Ref.from_record(check.body["measure_ref"]): check.body["measure_ref"]
                for check in checks
            }.values()
        )
        measure_admission_refs, control_rows = final_control_rows(
            view, readiness["check_refs"]
        )
        admissions = [
            view.read(Ref.from_record(ref), "measure_admission")
            for ref in measure_admission_refs
        ]
        measure_refs = [
            ref.as_record()
            for ref in dict.fromkeys(map(
                Ref.from_record,
                [*measure_refs, *(item.body["measure_ref"] for item in admissions)],
            ))
        ]
        grounding_observations = {}
        for admission in admissions:
            proposal = view.read(
                Ref.from_record(admission.body["proposal_ref"]), "measure_proposal"
            )
            acquired = authorize_acquisitions(view, proposal.body)
            grounding_observations.update(
                (record.ref, record) for record in acquired.observations
            )
        limitations = {
            Ref.from_record(ref): ref
            for observation in observations
            for ref in observation.body["limitation_refs"]
        }
        for reference in measure_refs:
            measure = view.data(Ref.from_record(reference))
            for ref in measure.get("limitation_refs", ()):
                reference = Ref.from_record(ref)
                view.data(reference)
                limitations[reference] = ref
        evidence_rows, run_bindings = _observation_rows(
            view, [*observations, *grounding_observations.values()]
        )
        checkpoint = view.head["latest_commit_id"]
        if (
            result.root_report.body["complete_index_ref"]
            != view.read(checkpoint, "commit").ref.as_record()
        ):
            raise DuetConflictError("campaign changed after the published root report")

    # Cross-store verification occurs outside the Duet writer transaction. A
    # changed campaign/authority cannot publish against this earlier snapshot.
    session.validate_registration(session.registration)
    manifest, specification = _source_build(session, receipt_record)
    execution_refs = _confirm_observations(session, evidence_rows)
    execution_refs.extend(
        confirm_control_evidence(
            session.store.evidence, control_rows, duet_id=session.duet_id
        )
    )
    execution_refs = list(
        {Ref.from_record(ref): ref for ref in execution_refs}.values()
    )
    with session.view() as view:
        session.store._authority(
            view.connection, session.duet_id, view.head["authority_head_id"]
        )
        if (
            view.head["latest_commit_id"] != checkpoint
            or view.candidate.ref != result.candidate.ref
            or canonical_json(root_readiness(view, assignment, session.policy))
            != canonical_json(readiness)
        ):
            raise DuetConflictError(
                "refinement changed during final build verification"
            )
        record = RefinementRecord(
            "verified_build",
            view.campaign_id,
            {
                "campaign_ref": view.contract.ref.as_record(),
                "target_approval_ref": view.contract.body["target_approval_ref"],
                "candidate_ref": result.candidate.ref.as_record(),
                "candidate_materialization_ref": result.candidate.body[
                    "materialization_ref"
                ],
                "source_admission_ref": source.ref.as_record(),
                "build_receipt_ref": source.body["build_receipt_ref"],
                "build_manifest_ref": Ref(
                    manifest.manifest_id, digest_record(manifest.as_record())
                ).as_record(),
                "materialized_specification_ref": Ref(
                    specification.specification_id, specification.content_hash
                ).as_record(),
                "requirement_catalog_ref": view.contract.body[
                    "requirement_catalog_ref"
                ],
                "mandatory_requirement_keys": readiness["mandatory_requirement_keys"],
                "check_refs": readiness["check_refs"],
                "measure_refs": measure_refs,
                "measure_admission_refs": measure_admission_refs,
                "observation_refs": readiness["observation_refs"],
                "validation_run_refs": execution_refs,
                "evaluation_run_refs": [
                    row.ref.as_record() for _, row in sorted(run_bindings.items())
                ],
                "grounding_refs": list(
                    {
                        Ref.from_record(ref): ref
                        for check in checks
                        for ref in check.body["grounding_refs"]
                    }.values()
                ),
                "limitation_refs": list(limitations.values()),
                "retained_warning_refs": readiness["retained_warning_refs"],
                "environment_ref": view.contract.body["environment_ref"],
                "root_report_ref": result.root_report.ref.as_record(),
                "root_unit_ref": unit.ref.as_record(),
                "continuation_ref": continuation.ref.as_record(),
                "refiner_run_ref": Ref(
                    result.run_evidence.evidence_id, result.run_evidence.content_hash
                ).as_record(),
                "complete_index_ref": result.root_report.body["complete_index_ref"],
            },
            view.contract.producer_ref,
            evidence_refs=tuple(
                dict.fromkeys(
                    ref
                    for row in [*observations, *admissions]
                    for ref in row.evidence_refs
                )
            ),
            predecessor_refs=(result.root_report.ref, source.ref),
            invocation_id=result.root_report.invocation_id,
        )
        exists = view.connection.execute(
            "SELECT 1 FROM artifacts WHERE artifact_id = ?", (record.artifact_id.value,)
        ).fetchone()
        session.store._put(view.connection, session.duet_id, record)
        if exists is None:
            session.store.duet_store._append_event(
                view.connection,
                duet_id=session.duet_id,
                event_type="refinement_build_verified",
                provenance="host_validation",
                record={"verified_build_ref": record.ref.as_record()},
            )
    return replace(result, verified_build=record)
