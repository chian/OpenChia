"""Read exact committed evidence; the worker cannot submit its own verdict."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from agent.duet_contracts import canonical_json, digest_record
from agent.duet_store import DuetStore
from agent.episode_contracts import OpaqueId, Sha256Digest
from episode_builder.store import BuildStore
from episode_runtime.store import RunStore
from episode_runtime.contracts import RunRegistration
from episode_runtime.records.experiments import read_reference
from function_library.epistemic_contract import exact
from function_library.refinement_checks import resolve_predicate

from .records import EvidenceRef, Ref, RefinementRecord, project


@dataclass(frozen=True)
class ResolvedEvidence:
    values: tuple[object, ...]
    references: Mapping[str, object]


class EvidenceReader:
    def __init__(self, duets: DuetStore, builds: BuildStore, runs: RunStore):
        self.duets, self.builds, self.runs = duets, builds, runs

    def reference(self, ref: Ref, duet_id: str) -> object:
        return read_reference(self.duets, ref.as_record(), duet_id)["record"]

    def approval(self, ref: Ref, duet_id: str | None = None) -> dict:
        row = self.duets.get_approval(ref.artifact_id.value)
        if (
            row is None
            or row.pop("revoked")
            or (duet_id is not None and row["duet_id"] != duet_id)
        ):
            raise ValueError("approval is absent, revoked, or has the wrong owner")
        if digest_record(row) != ref.content_hash:
            raise ValueError("approval digest does not match")
        return row

    def materialization_handoff(self, receipt, duet_id: str) -> dict:
        """Read the Builder's published baseline; never rerun or publish checks."""
        stored = self.builds.read_receipt(receipt.receipt_id)
        request = self.builds.read_build_request(stored.build_request_id)
        if stored != receipt or request.frozen_workflow.duet_id.value != duet_id:
            raise ValueError("materialization handoff belongs to another build or Duet")
        return self.builds.read_materialization_handoff(stored.receipt_id)

    def validate_contract(self, contract: RefinementRecord) -> dict:
        body = contract.body
        duet_id = body["duet_id"]
        target = self.approval(Ref.from_record(body["target_approval_ref"]), duet_id)
        self.approval(Ref.from_record(body["refiner_workflow_approval_ref"]))
        target_record = self.duets.get_artifact(target["artifact_id"])
        if (
            target_record is None
            or target_record["content_hash"] != target["content_hash"]
        ):
            raise ValueError("approved target artifact is absent or changed")
        for name in (
            "requirement_catalog_ref",
            "authority_ref",
            "policy_bundle_ref",
            "environment_ref",
            "final_projection_ref",
        ):
            self.reference(Ref.from_record(body[name]), duet_id)
        from episode_builder._contract_base import BuildReceipt

        receipt = BuildReceipt.from_record(
            self.reference(Ref.from_record(body["initial_build_receipt_ref"]), duet_id)
        )
        handoff = self.materialization_handoff(receipt, duet_id)
        catalog = self.reference(
            Ref.from_record(body["requirement_catalog_ref"]), duet_id
        )
        imported = self.reference(
            Ref.from_record(catalog["materialization_handoff_ref"]), duet_id
        )
        materialization = self.reference(
            Ref.from_record(body["initial_materialization_ref"]), duet_id
        )
        if canonical_json(imported) != canonical_json(handoff) or canonical_json(
            materialization
        ) != canonical_json(handoff["materialized_specification"]):
            raise ValueError(
                "campaign baseline differs from the exact published handoff"
            )
        return handoff

    def validate_candidate(self, candidate: RefinementRecord) -> None:
        for digest in candidate.body["files"].values():
            self.builds.read_blob(Sha256Digest(digest))

    def read(
        self, evidence: EvidenceRef, *, duet_id: str, allowed_runs: set[str]
    ) -> object:
        if evidence.store_kind == "duet_artifact":
            if evidence.owner_id.value != duet_id:
                raise ValueError("evidence belongs to another Duet")
            value = self.reference(
                Ref(evidence.record_id, evidence.content_hash), duet_id
            )
        elif evidence.store_kind == "run_audit":
            if evidence.owner_id.value not in allowed_runs:
                raise ValueError(
                    "Run evidence is outside the admitted evaluation lineage"
                )
            from episode_runtime.testing_harness.observations import (
                is_verified_run_path,
                resolve_observation,
                validate_observation_path,
            )

            if is_verified_run_path(evidence.observation_path):
                registration = self.runs.read_registration(evidence.owner_id)
                terminal = self.runs.read_evidence(evidence.owner_id)
                if (
                    evidence.record_id != terminal.terminal_event_id
                    or evidence.content_hash != terminal.head_event_hash
                ):
                    raise ValueError("Verified Run observation needs its exact terminal event anchor")
                selector = validate_observation_path(evidence.observation_path)
                return resolve_observation(
                    self.runs,
                    registration=registration,
                    evidence=terminal,
                    **selector,
                )
            events = self.runs.read_audit_log(evidence.owner_id)
            matches = [
                event for event in events if event.event_id == evidence.record_id
            ]
            if len(matches) != 1 or matches[0].event_hash != evidence.content_hash:
                raise ValueError("evidence does not name an exact committed Run event")
            value = matches[0].as_record()
        else:
            # Build evidence refers to a typed receipt, not an arbitrary blob
            # or a path chosen by the worker.
            receipt = self.builds.read_receipt(evidence.record_id)
            request = self.builds.read_build_request(receipt.build_request_id)
            if (
                request.frozen_workflow.duet_id.value != duet_id
                or receipt.build_request_id != evidence.owner_id
            ):
                raise ValueError("build evidence lineage does not match")
            value = receipt.as_record()
            if digest_record(value) != evidence.content_hash:
                raise ValueError("build evidence digest does not match")
        return project(value, evidence.observation_path)

    def resolve_attempt(self, attempt: RefinementRecord) -> ResolvedEvidence:
        # Campaign identity is selected on the host; neither the owner nor the
        # authorized validation Runs are derived from worker assertions.
        from .campaign_store import CampaignView

        with self.duets.transaction() as connection:
            view = CampaignView(connection, attempt.campaign_id)
            duet_id = view.head["duet_id"]
            contract = view.contract
            policy = self.reference(
                Ref.from_record(view.contract.body["policy_bundle_ref"]), duet_id
            )
        allowed_runs = set()
        references = {"policy": policy}
        payload = attempt.body["payload"]
        action = attempt.body["action"]
        if action in {"bind_measure_control", "observe_measure_control"}:
            from .measure_controls import resolve_control_attempt

            control_references, control_runs = resolve_control_attempt(self, attempt)
            references.update(control_references)
            allowed_runs.update(control_runs)
        if action in {"record_evaluation_source", "bind_evaluation_run"}:
            from .candidate_source import project_candidate_sources

            key = "source" if action == "record_evaluation_source" else "binding"
            record = RefinementRecord.from_record(payload[key])
            receipt_record = self.reference(
                Ref.from_record(record.body["build_receipt_ref"]), duet_id
            )
            inputs = self.builds.inspection_inputs_for_receipt(
                OpaqueId(receipt_record["receipt_id"])
            )
            if inputs.receipt.as_record() != receipt_record:
                raise ValueError(
                    "validation receipt differs from the existing BuildStore"
                )
            with self.duets.transaction() as connection:
                candidate = CampaignView(connection, attempt.campaign_id).read(
                    Ref.from_record(record.body["candidate_ref"]), "candidate"
                )
                request = CampaignView(connection, attempt.campaign_id).read(
                    Ref.from_record(record.body["request_ref"]), "evaluation"
                )
            projection = project_candidate_sources(
                self, contract, candidate, request.body
            )
            expected_plan = replace(
                projection.plan,
                build_request_id=inputs.build_request.build_request_id,
                build_attempt_id=inputs.build_attempt.build_attempt_id,
            )
            if inputs.plan.as_record() != expected_plan.as_record():
                raise ValueError(
                    "validation build changes the candidate's materialization plan"
                )
            if any(
                deficit.as_record()
                not in [item.as_record() for item in inputs.receipt.deficits]
                for deficit in projection.deficits
            ):
                raise ValueError(
                    "validation receipt omits a source preparation failure"
                )
            references.update({
                "build_receipt": receipt_record,
                "expected_source_files": projection.completed_files,
                "source_files": {
                    module.module_name.replace(".", "/")
                    + ".py": module.source_hash.value
                    for module in inputs.emitted_modules
                },
                "source_workflow": inputs.build_request.frozen_workflow.as_record(),
                "target_workflow": self.reference(
                    Ref.from_record(projection.scope.workflow_ref), duet_id
                ),
                "expected_source_authority": projection.scope.approval_ref,
                "source_authority": inputs.build_request.authority_approval.approval_id.value,
            })
            if action == "bind_evaluation_run":
                registration = RunRegistration.from_record(record.body["registration"])
                execution_scope = None
                stage = record.body.get("checking_gap") or (
                    record.body if "target_run_ref" in record.body else None
                )
                if stage is not None:
                    from .checking import prepare_checking

                    with self.duets.transaction() as connection:
                        view = CampaignView(connection, attempt.campaign_id)
                        target_binding = view.read(
                            Ref.from_record(stage["target_run_ref"]),
                            "evaluation_run",
                        )
                    prepared = prepare_checking(
                        self,
                        attempt.campaign_id,
                        Ref.from_record(record.body["request_ref"]),
                        target_binding,
                        Ref.from_record(stage["target_execution_ref"]),
                        request_id=registration.launch_request.request_id,
                    )
                    if prepared is None:
                        raise ValueError("evaluation has no approved checking workflow")
                    if "checking_gap" in record.body:
                        if prepared.gap is None:
                            raise ValueError(
                                "claimed checker prerequisite gap is no longer present"
                            )
                        references["checking_gap"] = prepared.gap
                    else:
                        if prepared.gap is not None:
                            raise ValueError(
                                "unavailable checker cannot bind an executable Run"
                            )
                        inputs = prepared.inputs
                        execution_scope = prepared.execution_scope
                        references["expected_checker_launch"] = (
                            prepared.launch.as_record()
                        )
                admitted = RunRegistration.from_admitted_build(
                    build_request=inputs.build_request,
                    build_attempt=inputs.build_attempt,
                    build_receipt=inputs.receipt,
                    build_manifest=inputs.manifest,
                    launch_request=registration.launch_request,
                    runtime_identity=registration.runtime_identity,
                    runtime_policy=registration.runtime_policy,
                    execution_scope=execution_scope,
                )
                references["admitted_registration"] = admitted.as_record()
                references["root_request_payload_contract"] = next(
                    node.request_payload_contract
                    for node in inputs.plan.nodes
                    if node.local_id == inputs.plan.root_local_id
                )
        if action == "apply_change":
            change = RefinementRecord.from_record(payload["change"])
            for operation in change.body["file_operations"]:
                exact(
                    operation,
                    {"kind", "logical_path", "before_hash", "after_blob_hash"},
                    "file operation",
                )
                if operation["after_blob_hash"] is not None:
                    self.builds.read_blob(Sha256Digest(operation["after_blob_hash"]))
            if change.body["implementation_detail_operations"]:
                from .materialization_edits import prepare_edits

                with self.duets.transaction() as connection:
                    candidate = CampaignView(connection, attempt.campaign_id).read(
                        Ref.from_record(change.body["expected_head_ref"]), "candidate"
                    )
                references["materialization_edit"] = prepare_edits(
                    self,
                    contract,
                    candidate,
                    change.body["implementation_detail_operations"],
                )
        if action == "select_action" and payload["retry_justification_ref"] is not None:
            self.reference(Ref.from_record(payload["retry_justification_ref"]), duet_id)
        if action == "observe":
            execution = Ref.from_record(payload["execution_ref"])
            run_id = OpaqueId(payload["run_id"])
            evidence = self.runs.read_evidence(run_id)
            if (
                evidence.content_hash != execution.content_hash
                or evidence.evidence_id != execution.artifact_id
            ):
                raise ValueError("execution evidence identity mismatch")
            registration = self.runs.read_registration(run_id)
            with self.duets.transaction() as connection:
                view = CampaignView(connection, attempt.campaign_id)
                binding = view.entry(
                    "evaluation_run", payload["request_ref"]["artifact_id"]
                ).record
            if canonical_json(registration.as_record()) != canonical_json(
                binding.body["registration"]
            ):
                raise ValueError(
                    "observation Run is not the bound target or approved checker"
                )
            allowed_runs.add(run_id.value)
            references["execution"] = evidence.as_record()
            references["registration"] = registration.as_record()
        if action == "install_check":
            check = RefinementRecord.from_record(payload["check"])
            selection = self.reference(
                Ref.from_record(check.body["predicate_ref"]), duet_id
            )
            resolve_predicate(selection)
            references["predicate"] = selection
            expected_interface = {
                "materialization": "materialization.validation",
                "execution": "refinement.predicate",
            }[check.body["evidence_kind"]]
            if selection["interface"] != expected_interface:
                raise ValueError(
                    "check's evidence kind differs from its registered predicate"
                )
        if action == "observe_materialization":
            from episode_builder._contract_base import BuildReceipt
            from .candidate_source import materialization_results

            request_ref = Ref.from_record(payload["request_ref"])
            with self.duets.transaction() as connection:
                view = CampaignView(connection, attempt.campaign_id)
                request = view.read(request_ref, "evaluation")
                candidate = view.read(
                    Ref.from_record(request.body["candidate_ref"]), "candidate"
                )
                check = view.entry("check", payload["check_key"]).record
                source = view.entry(
                    "evaluation_source", request.artifact_id.value
                ).record
            receipt = BuildReceipt.from_record(
                self.reference(
                    Ref.from_record(source.body["build_receipt_ref"]), duet_id
                )
            )
            outcomes = materialization_results(self, contract, candidate, receipt)
            references["materialization_result"] = outcomes[
                check.body["expected"]["check_id"]
            ]
            references["predicate"] = self.reference(
                Ref.from_record(check.body["predicate_ref"]), duet_id
            )
            resolve_predicate(references["predicate"])
        if action == "propose_measure" and "proposal" in payload:
            proposal = RefinementRecord.from_record(payload["proposal"])
            with self.duets.transaction() as connection:
                assignment = (
                    CampaignView(connection, attempt.campaign_id)
                    .entry("invocation", attempt.body["invocation_id"])
                    .record
                )
            goal = self.reference(
                Ref.from_record(assignment.body["goal_record_ref"]), duet_id
            )
            references["measure_request"] = goal["measure_request"]
            for field, value in proposal.body.items():
                if field in {"assignment_ref", "owner_assignment_ref"}:
                    continue
                selected = (
                    [value]
                    if field.endswith("_ref")
                    else value
                    if field.endswith("_refs")
                    else ()
                )
                for ref in selected:
                    self.reference(Ref.from_record(ref), duet_id)
            resolve_predicate(
                self.reference(
                    Ref.from_record(proposal.body["decision_function_ref"]), duet_id
                )
            )
        if action == "observe":
            with self.duets.transaction() as connection:
                check = (
                    CampaignView(connection, attempt.campaign_id)
                    .entry("check", payload["check_key"])
                    .record
                )
            references["predicate"] = self.reference(
                Ref.from_record(check.body["predicate_ref"]), duet_id
            )
        values = tuple(
            self.read(ref, duet_id=duet_id, allowed_runs=allowed_runs)
            for ref in attempt.evidence_refs
        )
        return ResolvedEvidence(values, references)
