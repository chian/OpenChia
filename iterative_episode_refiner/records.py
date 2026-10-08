"""Immutable campaign records. Stored proposals are not operative state.

The envelope is shared with no authority implied by its presence in DuetStore.
Only the campaign publication boundary may install its typed projections.

``target_workflow_ref`` names the Target Workflow being refined. A
``candidate_ref`` names one exact candidate revision, not the workflow itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Mapping

from agent.duet_contracts import canonical_json, content_id, digest_record
from agent.episode_contracts import OpaqueId, Sha256Digest
from function_library.epistemic_contract import exact, names
from function_library.models import _freeze_json, _thaw_json
from function_library.refinement_contract import CHILDREN as ROLES


# These closed record shapes are schema version 1, not inline model schemas.
RECORD_FIELDS = {
    "campaign": {
        "duet_id",
        "target_approval_ref",
        "target_workflow_ref",
        "initial_build_inputs_ref",
        "initial_materialization_ref",
        "refiner_workflow_approval_ref",
        "refiner_manifest_ref",
        "requirement_catalog_ref",
        "authority_ref",
        "policy_bundle_ref",
        "environment_ref",
        "guidance_catalog_ref",
        "final_projection_ref",
        "instrument_builds_ref",
    },
    "candidate": {
        "parent_candidate_ref",
        "target_approval_ref",
        "materialization_ref",
        "files",
        "implementation_directive_refs",
        "change_set_ref",
        "source_admission_ref",
    },
    "materialization": {"baseline_ref", "plan", "changed_targets", "instrument_plans"},
    "assignment": {
        "parent_assignment_ref",
        "coordinating_invocation_id",
        "role",
        "scope_requirement_keys",
        "contribution_requirement_keys",
        "scope_partition_ref",
        "owned_slice_keys",
        "baseline_candidate_ref",
        "goal_record_ref",
        "authority_ref",
        "input_refs",
        "preservation_requirement_keys",
        "dependency_refs",
        "local_measure_ref",
        "acceptance_measure_ref",
        "progress_manifest_ref",
        "allowed_action_classes",
        "allowed_child_bindings",
        "instruction_refs",
        "history_query_ref",
        "return_projection_ref",
        "control_bundle_ref",
        "supersedes_assignment_refs",
        "writable_paths",
        "materialization_targets",
        "protected_paths",
        "judgment_lineage",
    },
    "change": {
        "assignment_ref",
        "design_plan_ref",
        "expected_head_ref",
        "file_operations",
        "implementation_detail_operations",
        "findings",
        "rationale_claim_refs",
    },
    "design_plan": {
        "assignment_ref",
        "approach_key",
        "requirement_mapping",
        "assumption_refs",
        "proposed_component_refs",
        "intended_change_scope",
        "intended_materialization_targets",
        "dependency_effects",
        "local_measure_ref",
        "acceptance_measure_ref",
        "preservation_measure_refs",
        "expected_observation_refs",
        "falsifying_observation_refs",
        "open_need_refs",
    },
    "check": {
        "requirement_key",
        "evidence_kind",
        "origin_refs",
        "measure_ref",
        "purpose",
        "predicate_ref",
        "expected",
        "dependency_paths",
        "environment_ref",
        "mandatory",
        "guard_keys",
        "grounding_refs",
        "observation_path",
        "execution_binding",
    },
    "measure_proposal": {
        "components",
        "assignment_ref",
        "owner_assignment_ref",
        "basis_ref",
        "requirement_keys",
        "purpose",
        "oracle_kind",
        "oracle_ref",
        "input_domain_ref",
        "case_manifest_ref",
        "observation_schema_ref",
        "decision_function_ref",
        "positive_control_refs",
        "negative_control_refs",
        "grounding_refs",
        "independence_policy_ref",
        "uncertainty_policy_ref",
        "limitation_refs",
        "instrument_return_ref",
        "grounding_acquisition_refs",
        "reviewed_definition_ref",
    },
    "measure_definition": {"assignment_ref", "owner_assignment_ref", "requirement_catalog_ref", "design"},
    "measure_review": {"assignment_ref", "definition_ref", "criteria", "counterexamples", "limitations"},
    "measure_prerequisite": {"assignment_ref", "owner_assignment_ref", "need", "explanation"},
    "measure_admission": {
        "proposal_ref",
        "owner_assignment_ref",
        "measure_ref",
        "check_refs",
        "measurement_function",
        "evaluation_binding",
        "evaluation_bindings",
        "control_results",
        "control_snapshot",
        "requirement_results",
        "limitation_refs",
        "grounding_refs",
        "status",
        "reason",
        "fact_keys",
        "control_run_refs",
    },
    "measure_control_run": {
        "proposal_ref",
        "grounding_ref",
        "control_ref",
        "registration",
        "gap",
    },
    "measure_control_observation": {
        "control_run_ref",
        "execution_ref",
        "observed_value",
        "outcome",
        "error",
    },
    "evaluation": {
        "candidate_ref",
        "measure_ref",
        "check_keys",
        "input_refs",
        "environment_ref",
        "harness_ref",
        "purpose",
        "parent_operation_id",
        "capability_ref",
        "availability",
        "selection_check_keys",
    },
    "evaluation_source": {
        "request_ref",
        "candidate_ref",
        "build_receipt_ref",
        "admitted",
    },
    "evaluation_run": {
        "request_ref",
        "candidate_ref",
        "registration",
        "build_receipt_ref",
        "target_run_ref",
        "target_execution_ref",
        "checking_gap",
    },
    "observation": {
        "request_ref",
        "execution_ref",
        "checked_dependency_hashes",
        "check_key",
        "observed_value",
        "outcome",
        "counterexample_refs",
        "limitation_refs",
    },
    "research_source": {
        "assignment_ref", "operation", "query", "source_id", "kind", "title",
        "url", "path", "content", "content_hash", "truncated", "redacted",
    },
    "research_finding": {
        "assignment_ref", "owner_assignment_ref", "candidate_ref", "role",
        "requirement_key", "state", "answer", "applicability", "limitations",
        "source_refs",
    },
    "parent_assessment": {
        "assignment_ref",
        "check_key",
        "candidate_ref",
        "checked_dependency_hashes",
        "source_report_refs",
        "source_observation_refs",
        "outcome",
    },
    "prerequisite_assessment": {
        "assignment_ref",
        "source_report_ref",
        "source_record_ref",
        "decision",
        "fact_keys",
    },
    "lesson": {
        "requirement_keys",
        "action_class",
        "action_inputs",
        "environment_ref",
        "supporting_observation_refs",
        "policy_effect",
        "reopening_conditions",
        "equivalence_key",
        "fact_keys",
    },
    "conflict": {
        "requirement_keys",
        "observation_refs",
        "transition_refs",
        "kind",
        "scope_owner_invocation_id",
        "involved_assignment_refs",
        "applicability_ref",
        "state",
        "resolution_ref",
    },
    "coordination": {
        "conflict_ref",
        "joint_assignment_ref",
        "original_assignment_refs",
        "required_check_keys",
    },
    "conflict_resolution": {
        "conflict_ref",
        "coordination_ref",
        "candidate_ref",
        "observation_refs",
        "required_check_keys",
    },
    "attempt": {
        "operation_id",
        "invocation_id",
        "logical_unit_id",
        "action",
        "payload",
    },
    "selection": {
        "action_class",
        "action_inputs",
        "candidate_ref",
        "considered_lesson_refs",
        "retry_justification_ref",
    },
    "continuation": {
        "numeric_step",
        "remaining_opportunities",
        "prior_remaining_opportunities",
        "attained",
        "observation_keys",
        "usable_observation",
        "stop",
        "numeric_control",
        "opportunity_function",
    },
    "local_context": {
        "assignment_ref",
        "invocation_id",
        "current_candidate_ref",
        "local_measure_ref",
        "check_states",
        "assessment_refs",
        "prerequisite_assessment_refs",
        "eligible_actions",
        "applicable_lesson_refs",
        "reopened_lesson_refs",
        "conflict_refs",
        "recent_unit_refs",
        "history_cursor",
        "complete_index_ref",
    },
    "commit": {"previous_commit_ref", "sequence", "attempt_ref", "deltas"},
    "unit_receipt": {
        "assignment_ref",
        "local_measure_ref",
        "judgment_lineage",
        "invocation_id",
        "logical_unit_id",
        "ordinal",
        "stage_receipt_refs",
        "candidate_before_ref",
        "candidate_after_ref",
        "evaluation_refs",
        "assessment_refs",
        "prerequisite_assessment_refs",
        "invalidated_check_keys",
        "conflict_refs",
        "lesson_refs",
        "semantic_fact_keys",
        "credit_before",
        "credit_after",
        "realized_yield",
        "continuation_ref",
        "disposition",
        "decision_request_ref",
    },
    "parent_report": {
        "return_value",
        "assignment_ref",
        "invocation_id",
        "role",
        "scope_requirement_keys",
        "selected_candidate_ref",
        "examined_candidate_refs",
        "measure_refs",
        "measure_proposal_refs",
        "measure_admission_refs",
        "source_admission_refs",
        "determinations",
        "investigation_findings",
        "assessment_refs",
        "prerequisite_assessment_refs",
        "preservation_findings",
        "relevant_attempt_refs",
        "lesson_refs",
        "unresolved_requirement_keys",
        "decision_request_refs",
        "implementation_findings_ref",
        "child_report_refs",
        "conflict_refs",
        "termination",
        "continuation_ref",
        "complete_index_ref",
    },
    "verified_build": {
        "campaign_ref",
        "target_approval_ref",
        "candidate_ref",
        "candidate_materialization_ref",
        "source_admission_ref",
        "build_receipt_ref",
        "build_manifest_ref",
        "materialized_specification_ref",
        "requirement_catalog_ref",
        "mandatory_requirement_keys",
        "check_refs",
        "measure_refs",
        "measure_admission_refs",
        "observation_refs",
        "validation_run_refs",
        "evaluation_run_refs",
        "grounding_refs",
        "limitation_refs",
        "retained_warning_refs",
        "environment_ref",
        "root_report_ref",
        "root_unit_ref",
        "continuation_ref",
        "refiner_run_ref",
        "complete_index_ref",
    },
    "review_handoff": {
        "campaign_ref",
        "baseline_ref",
        "target_approval_ref",
        "candidate_ref",
        "root_report_ref",
        "refiner_run_ref",
        "has_terminal_report",
        "disposition",
        "decision_refs",
        "source_admission_refs",
        "verified_build_ref",
        "verification_gaps",
        "complete_index_ref",
    },
}

# Earlier v1 receipts/projections have no parent-assessment links. Keep their
# exact bodies and hashes readable; new producers always emit this field.
_OPTIONAL_FIELDS = {
    kind: {"assessment_refs", "prerequisite_assessment_refs"}
    for kind in ("unit_receipt", "parent_report", "local_context")
}
_OPTIONAL_FIELDS["parent_report"].add("measure_admission_refs")
_OPTIONAL_FIELDS["parent_report"].add("investigation_findings")
_OPTIONAL_FIELDS["parent_report"].add("child_report_refs")
_OPTIONAL_FIELDS["evaluation"] = {"availability", "selection_check_keys"}
_OPTIONAL_FIELDS["check"] = {"execution_binding"}
_OPTIONAL_FIELDS["measure_admission"] = {"evaluation_bindings", "control_run_refs"}
_OPTIONAL_FIELDS["measure_prerequisite"] = {"explanation"}
_OPTIONAL_FIELDS["measure_control_run"] = {"experiment_ref"}
_OPTIONAL_FIELDS["continuation"] = {"prior_remaining_opportunities"}
_OPTIONAL_FIELDS["evaluation_run"] = {
    "experiment_ref",
    "target_run_ref",
    "target_execution_ref",
    "checking_gap",
}
_OPTIONAL_FIELDS["verified_build"] = {"measure_admission_refs"}
_OPTIONAL_FIELDS["campaign"] = {"instrument_builds_ref"}
_OPTIONAL_FIELDS["materialization"] = {"instrument_plans"}
_OPTIONAL_FIELDS["measure_proposal"] = {
    "instrument_return_ref",
    "grounding_acquisition_refs",
    "reviewed_definition_ref",
}


@dataclass(frozen=True)
class Ref:
    artifact_id: OpaqueId
    content_hash: Sha256Digest

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_id, OpaqueId) or not isinstance(
            self.content_hash, Sha256Digest
        ):
            raise ValueError("references require an opaque ID and exact digest")

    def as_record(self) -> dict:
        return {
            "artifact_id": self.artifact_id.value,
            "content_hash": self.content_hash.value,
        }

    @classmethod
    def from_record(cls, value: object) -> Ref:
        row = exact(value, {"artifact_id", "content_hash"}, "artifact reference")
        return cls(OpaqueId(row["artifact_id"]), Sha256Digest(row["content_hash"]))


@dataclass(frozen=True)
class EvidenceRef:
    store_kind: str
    owner_id: OpaqueId
    record_id: OpaqueId
    content_hash: Sha256Digest
    observation_path: str

    def __post_init__(self) -> None:
        if self.store_kind not in {"duet_artifact", "build_artifact", "run_audit"}:
            raise ValueError("unknown evidence store")
        Ref(self.record_id, self.content_hash)
        if not isinstance(self.owner_id, OpaqueId):
            raise ValueError("evidence needs an owner identity")
        pointer_parts(self.observation_path)

    def as_record(self) -> dict:
        return {
            "store_kind": self.store_kind,
            "owner_id": self.owner_id.value,
            "record_id": self.record_id.value,
            "content_hash": self.content_hash.value,
            "observation_path": self.observation_path,
        }

    @classmethod
    def from_record(cls, value: object) -> EvidenceRef:
        row = exact(value, set(cls.__dataclass_fields__), "evidence reference")
        return cls(
            row["store_kind"],
            OpaqueId(row["owner_id"]),
            OpaqueId(row["record_id"]),
            Sha256Digest(row["content_hash"]),
            row["observation_path"],
        )


def pointer_parts(pointer: str) -> tuple[str, ...]:
    if not isinstance(pointer, str) or "\x00" in pointer or len(pointer) > 2048:
        raise ValueError("invalid observation pointer")
    if not pointer:
        return ()
    if not pointer.startswith("/"):
        raise ValueError("observation pointer must start with /")
    result = []
    for part in pointer[1:].split("/"):
        # An escaped tilde is decoded only once (RFC 6901).
        remaining = part.replace("~0", "").replace("~1", "")
        if "~" in remaining:
            raise ValueError("invalid JSON pointer escape")
        result.append(part.replace("~1", "/").replace("~0", "~"))
    return tuple(result)


def project(value: object, pointer: str) -> object:
    for part in pointer_parts(pointer):
        if isinstance(value, Mapping):
            value = value[part]
        elif isinstance(value, (tuple, list)) and (
            part == "0" or (part.isdecimal() and not part.startswith("0"))
        ):
            value = value[int(part)]
        else:
            raise ValueError("observation pointer does not resolve")
    return value


def logical_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("candidate paths must be relative POSIX paths")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("candidate path escapes or aliases its namespace")
    return value


def _execution_binding(value):
    binding = exact(
        value,
        {"harness_ref", "capability_ref", "input_refs"},
        "check execution binding",
    )
    Ref.from_record(binding["harness_ref"])
    Ref.from_record(binding["capability_ref"])
    if not isinstance(binding["input_refs"], (list, tuple)):
        raise ValueError("check input references must be an array")
    for ref in binding["input_refs"]:
        Ref.from_record(ref)


def _validate_control_record(kind, body):
    if kind == "measure_control_observation":
        if body["outcome"] not in {"pass", "fail", "inconclusive", "error"}:
            raise ValueError("invalid executable-control outcome")
        if body["error"] is not None and not isinstance(body["error"], str):
            raise ValueError("control error must be text data or null")
        if (body["outcome"] == "error") != (body["error"] is not None):
            raise ValueError(
                "control errors cannot masquerade as pass/fail observations"
            )
        return
    if (body["registration"] is None) == (body["gap"] is None):
        raise ValueError(
            "a control requires either a Run registration or a prerequisite gap"
        )
    if body["gap"] is not None:
        gap = exact(body["gap"], {"kind", "detail"}, "control prerequisite gap")
        if gap["kind"] not in {
            "checker_source_unavailable",
            "checker_source_invalid",
            "checker_input_invalid",
        }:
            raise ValueError("unregistered executable-control gap")
        if not isinstance(gap["detail"], str):
            raise ValueError("control prerequisite detail must be text data")


def _validate_measure_need(need):
    exact(
        need,
        {
            "need_key",
            "kind",
            "purpose",
            "requirement_keys",
            "basis_refs",
            "instrument_build_ref",
        },
        "measurement prerequisite need",
    )
    OpaqueId(need["need_key"])
    names(need["requirement_keys"], "measurement need requirements", nonempty=True)
    if need["kind"] not in {
        "measure_authority_required",
        "grounding_required",
        "instrument_build_required",
    } or need["purpose"] not in {"local", "acceptance", "composition", "adequacy"}:
        raise ValueError("measurement prerequisite kind or purpose is invalid")
    if not isinstance(need["basis_refs"], (list, tuple)) or not need["basis_refs"]:
        raise ValueError("measurement prerequisite needs committed basis references")
    for reference in need["basis_refs"]:
        Ref.from_record(reference)
    if (need["instrument_build_ref"] is not None) != (
        need["kind"] == "instrument_build_required"
    ):
        raise ValueError("instrument-building request needs its exact specification")
    if need["instrument_build_ref"] is not None:
        Ref.from_record(need["instrument_build_ref"])


def _validate_requirement_results(rows):
    if not isinstance(rows, (list, tuple)) or not rows:
        raise ValueError("measure admission needs explicit per-requirement results")
    keys = []
    for row in rows:
        exact(row, {"requirement_key", "status", "reason", "cases"}, "requirement adequacy result")
        names((row["requirement_key"],), "requirement adequacy key", nonempty=True)
        keys.append(row["requirement_key"])
        if row["status"] not in {"pass", "fail", "error", "blocked"}:
            raise ValueError("requirement adequacy must distinguish failure from missing evidence")
        if row["reason"] is not None and not isinstance(row["reason"], str):
            raise ValueError("requirement adequacy reason must be text or null")
        if not isinstance(row["cases"], (list, tuple)):
            raise ValueError("requirement adequacy cases must be an array")
        states = set()
        references = []
        for case in row["cases"]:
            exact(case, {"grounding_ref", "requirement_key", "status", "reason",
                         "controls_total", "controls_matched"}, "case adequacy result")
            references.append(Ref.from_record(case["grounding_ref"]))
            if case["requirement_key"] != row["requirement_key"]:
                raise ValueError("case adequacy belongs to another requirement")
            if case["status"] not in {"pass", "fail", "error", "blocked"}:
                raise ValueError("case adequacy has an unknown status")
            if case["reason"] is not None and not isinstance(case["reason"], str):
                raise ValueError("case adequacy reason must be text or null")
            total, matched = case["controls_total"], case["controls_matched"]
            if type(total) is not int or type(matched) is not int or not 0 <= matched <= total or total < 2:
                raise ValueError("case adequacy has invalid control counts")
            if (case["status"] == "pass") != (matched == total):
                raise ValueError("case adequacy pass requires every control to match")
            states.add(case["status"])
        if len(set(references)) != len(references):
            raise ValueError("requirement adequacy repeats a case")
        expected = next((status for status in ("error", "fail", "blocked") if status in states),
                        "pass" if states else "blocked")
        if row["status"] != expected:
            raise ValueError("requirement adequacy differs from its case results")
    if len(set(keys)) != len(keys):
        raise ValueError("measure admission repeats a requirement result")


def _validate_body(kind: str, body: Mapping) -> None:
    if kind not in RECORD_FIELDS:
        raise ValueError("unregistered refinement record kind")
    optional = _OPTIONAL_FIELDS.get(kind, set())
    exact(body, (RECORD_FIELDS[kind] - optional) | (set(body) & optional), f"{kind} v1")
    for key, value in body.items():
        if key.endswith("_refs"):
            if not isinstance(value, (tuple, list)):
                raise ValueError(f"{key} must be an array")
            for ref in value:
                Ref.from_record(ref)
        elif key.endswith("_ref") and value is not None:
            Ref.from_record(value)
    if kind in {"measure_control_run", "measure_control_observation"}:
        _validate_control_record(kind, body)
    if kind == "research_source":
        from hashlib import sha256

        for key in ("operation", "source_id", "kind", "title"):
            names((body[key],), f"research {key}")
        source_kinds = {"web_search": "web_search", "read_url": "web_page",
                        "library_search": "library", "read_library": "library",
                        "read_candidate": "candidate"}
        if source_kinds.get(body["operation"]) != body["kind"]:
            raise ValueError("research source kind differs from its retrieval operation")
        if not isinstance(body["query"], Mapping) or not isinstance(body["content"], str):
            raise ValueError("research source needs its retrieval arguments and text")
        for key in ("url", "path"):
            if body[key] is not None:
                names((body[key],), f"research {key}")
        if any(type(body[key]) is not bool for key in ("truncated", "redacted")):
            raise ValueError("research source must declare truncation and redaction")
        if sha256(body["content"].encode("utf-8")).hexdigest() != body["content_hash"]:
            raise ValueError("research content differs from its persisted digest")
    if kind == "research_finding":
        from .investigation import RESEARCH_STATES, RESEARCH_TEXT_LIMITS, research_resolved

        if body["role"] not in RESEARCH_STATES or body["state"] not in RESEARCH_STATES[body["role"]]:
            raise ValueError("research finding has an unknown role or advisory state")
        for key in ("requirement_key", "answer", "applicability"):
            names((body[key],), f"research {key}")
        for key in ("answer", "applicability"):
            if len(body[key]) > RESEARCH_TEXT_LIMITS[key]:
                raise ValueError(f"research {key} exceeds its {RESEARCH_TEXT_LIMITS[key]}-character synthesis format")
        names(body["limitations"], "research limitations")
        if len(body["limitations"]) > RESEARCH_TEXT_LIMITS["limitations"]:
            raise ValueError(f"research synthesis allows at most {RESEARCH_TEXT_LIMITS['limitations']} limitations")
        if any(len(item) > RESEARCH_TEXT_LIMITS["limitation"] for item in body["limitations"]):
            raise ValueError(f"each research limitation must fit {RESEARCH_TEXT_LIMITS['limitation']} characters")
        refs = [Ref.from_record(ref) for ref in body["source_refs"]]
        if len(refs) != len(set(refs)):
            raise ValueError("research finding repeats a source")
        if body["state"] != "unresolved" and not refs:
            raise ValueError("a determinate research finding needs inspected sources")
    if kind == "measure_prerequisite":
        _validate_measure_need(body["need"])
        if "explanation" in body:
            names((body["explanation"],), "measurement prerequisite explanation", nonempty=True)
    if kind == "measure_definition":
        from .measure_design import validate_design

        validate_design(body["design"])
    if kind == "measure_review":
        from .measure_design import validate_review

        validate_review({key: value for key, value in body.items() if key != "assignment_ref"})
    if kind == "measure_proposal" and "instrument_return_ref" in body:
        Ref.from_record(body["instrument_return_ref"])
    if kind == "review_handoff":
        if type(body["has_terminal_report"]) is not bool:
            raise ValueError(
                "review must distinguish a terminal report from a last-known snapshot"
            )
        if not isinstance(body["disposition"], str) or not isinstance(
            body["verification_gaps"], (tuple, list)
        ):
            raise ValueError(
                "review requires an explicit disposition and typed verification gaps"
            )
        if body["verified_build_ref"] is not None and (
            not body["has_terminal_report"]
            or body["disposition"] != "attained"
            or body["verification_gaps"]
        ):
            raise ValueError(
                "an unresolved or external return cannot carry verified readiness"
            )
    if kind == "evaluation_run" and (
        ("target_run_ref" in body) != ("target_execution_ref" in body)
        or (
            "target_run_ref" in body
            and (body["target_run_ref"] is None or body["target_execution_ref"] is None)
        )
    ):
        raise ValueError(
            "checking Run needs both its target binding and execution evidence"
        )
    if kind == "evaluation_run" and "checking_gap" in body:
        if "target_run_ref" in body:
            raise ValueError("an unavailable checker cannot have a checker Run binding")
        gap = exact(
            body["checking_gap"],
            {"kind", "detail", "target_run_ref", "target_execution_ref"},
            "checking prerequisite gap",
        )
        if gap["kind"] not in {
            "checker_source_unavailable",
            "checker_source_invalid",
            "checker_input_invalid",
        }:
            raise ValueError("unregistered checking prerequisite gap")
        if not isinstance(gap["detail"], str):
            raise ValueError("checking gap detail must be text data")
        for field in ("target_run_ref", "target_execution_ref"):
            Ref.from_record(gap[field])
    if kind == "verified_build":
        names(
            body["mandatory_requirement_keys"], "verified requirements", nonempty=True
        )
        if not body["check_refs"] or len(body["check_refs"]) != len(
            body["observation_refs"]
        ):
            raise ValueError("verified build needs one observation per required check")
    if kind == "candidate":
        if not isinstance(body["files"], Mapping):
            raise ValueError("candidate files must be a path to digest mapping")
        for path, digest in body["files"].items():
            logical_path(path)
            Sha256Digest(digest)
    if kind == "materialization" and "instrument_plans" in body:
        if not isinstance(body["instrument_plans"], Mapping):
            raise ValueError("instrument plans require exact build identities")
        for key, revision in body["instrument_plans"].items():
            OpaqueId(key)
            exact(revision, {"baseline_ref", "plan"}, "instrument plan revision")
            Ref.from_record(revision["baseline_ref"])
            if not isinstance(revision["plan"], Mapping):
                raise ValueError("instrument revision requires a typed plan body")
    if kind == "assignment":
        if body["role"] not in ROLES:
            raise ValueError("unregistered refinement role")
        OpaqueId(body["coordinating_invocation_id"])
        OpaqueId(body["judgment_lineage"])
        for key in (
            "scope_requirement_keys",
            "contribution_requirement_keys",
            "owned_slice_keys",
            "allowed_action_classes",
        ):
            names(body[key], key, nonempty=True)
        scope = set(body["scope_requirement_keys"])
        if not set(body["contribution_requirement_keys"]).issubset(scope):
            raise ValueError(
                "contribution requirements must be inside the assigned scope"
            )
        if not set(
            names(body["preservation_requirement_keys"], "preservation requirements")
        ).issubset(scope):
            raise ValueError(
                "preservation requirements must be inside the assigned scope"
            )
        for key in ("writable_paths", "protected_paths"):
            for path in names(body[key], key):
                logical_path(path)
        for pointer in names(body["materialization_targets"], "materialization targets"):
            pointer_parts(pointer)
    if kind == "change":
        if not isinstance(body["findings"], (list, tuple)):
            raise ValueError("implementation findings must be a list")
        for finding in body["findings"]:
            exact(finding, {"requirement_key", "blocker", "needed_change"}, "implementation finding")
            for field in finding:
                names((finding[field],), field)
    if kind == "design_plan":
        for path in names(body["intended_change_scope"], "intended source paths"):
            logical_path(path)
        for pointer in names(body["intended_materialization_targets"], "intended materialization targets"):
            pointer_parts(pointer)
    if kind == "unit_receipt":
        OpaqueId(body["judgment_lineage"])
    if kind == "check":
        names((body["requirement_key"],), "requirement key", nonempty=True)
        if body["evidence_kind"] not in {"execution", "materialization", "checking_program"}:
            raise ValueError("check must distinguish runtime from static evidence")
        if type(body["mandatory"]) is not bool or not body["grounding_refs"]:
            raise ValueError("check requires explicit mandatory status and grounding")
        pointer_parts(body["observation_path"])
        if "execution_binding" in body:
            _execution_binding(body["execution_binding"])
        if body["dependency_paths"] is not None:
            for path in names(body["dependency_paths"], "dependency paths"):
                logical_path(path)
    if kind == "measure_admission":
        _validate_requirement_results(body["requirement_results"])
        from function_library.materialization_progress import RequirementMeasure

        if not isinstance(body["control_snapshot"], Mapping):
            raise ValueError("measure admission needs its pinned control evidence")
        for key, reference in body["control_snapshot"].items():
            OpaqueId(key)
            Ref.from_record(reference)
        facts = names(body["fact_keys"], "instrument adequacy facts")
        if len(facts) != sum(row["status"] == "pass" for row in body["requirement_results"]):
            raise ValueError("instrument progress needs exactly one fact per adequate requirement")
        if body["status"] not in {"admitted", "partial", "rejected"}:
            raise ValueError("measure admission must state admitted, partial or rejected")
        if body["status"] == "admitted":
            measure = RequirementMeasure.from_record(body["measurement_function"])
            requirements = {row["requirement_id"] for row in measure.requirements}
            assessed = {row["requirement_key"] for row in body["requirement_results"]}
            if not assessed <= requirements:
                raise ValueError("composite measure omits its assessed requirements")
            check_ids = {ref["artifact_id"] for ref in body["check_refs"]}
            if any((row["requirement_id"] in assessed and not row["check_ids"])
                   or not set(row["check_ids"]) <= check_ids
                   for row in measure.requirements):
                raise ValueError("admitted composite needs its exact checks for every requirement")
            if any(row["status"] != "pass" for row in body["requirement_results"]):
                raise ValueError("an admitted composite requires adequate checks for every requirement")
        elif body["measurement_function"] is not None:
            raise ValueError("an incomplete measure retains components without publishing a callable")
        if body["status"] == "partial" and not body["check_refs"]:
            raise ValueError("partial measure construction needs adequate component checks")
        if body["status"] == "rejected" and (body["check_refs"] or facts):
            raise ValueError("a rejected instrument has no adequate components")
    if kind == "measure_admission" and "evaluation_bindings" in body:
        bindings = body["evaluation_bindings"]
        if (
            body["evaluation_binding"] is not None
            or not isinstance(bindings, (list, tuple))
            or len(bindings) < 2
        ):
            raise ValueError(
                "multi-context admission must use only its explicit binding set"
            )
        if len({canonical_json(binding) for binding in bindings}) != len(bindings):
            raise ValueError("measure instrument bindings must be unique")
        for binding in bindings:
            exact(
                binding,
                {
                    "measure_ref",
                    "purpose",
                    "harness_ref",
                    "capability_ref",
                    "input_refs",
                },
                "measure execution binding",
            )
            if binding["measure_ref"] != body["measure_ref"]:
                raise ValueError("instrument binding belongs to another measure")
            names((binding["purpose"],), "instrument purpose", nonempty=True)
            _execution_binding({
                field: binding[field]
                for field in ("harness_ref", "capability_ref", "input_refs")
            })
    if kind == "evaluation" and "availability" in body:
        availability = exact(
            body["availability"], {"executable", "gaps"}, "evaluation availability"
        )
        if type(availability["executable"]) is not bool:
            raise ValueError(
                "evaluation availability needs an explicit execution decision"
            )
        if not isinstance(availability["gaps"], (list, tuple)):
            raise ValueError("evaluation gaps must be an array")
        for gap in availability["gaps"]:
            exact(
                gap,
                {"kind", "detail", "requirement_keys", "check_keys"},
                "evaluation gap",
            )
            if gap["kind"] not in {
                "coverage_missing",
                "checks_unavailable",
                "guards_unavailable",
                "environment_mismatch",
                "instrument_missing",
                "instrument_ambiguous",
                "instrument_route_unavailable",
                "launch_input_invalid",
            }:
                raise ValueError("unknown evaluation gap")
            names((gap["detail"],), "evaluation gap detail", nonempty=True)
            names(gap["requirement_keys"], "evaluation gap requirements")
            names(gap["check_keys"], "evaluation gap checks")
    if kind == "evaluation" and "selection_check_keys" in body:
        names(body["selection_check_keys"], "investigation selection", nonempty=True)
    if kind == "parent_assessment":
        if body["outcome"] not in {"pass", "fail", "inconclusive"}:
            raise ValueError("parent assessment requires a measured determination")
        if not body["source_report_refs"] or not body["source_observation_refs"]:
            raise ValueError(
                "parent assessment must retain the returned original evidence"
            )
    if kind == "prerequisite_assessment":
        decision = body["decision"]
        if not isinstance(decision, Mapping):
            raise ValueError("prerequisite decision must be a typed object")
        decision_kind = decision.get("kind")
        common = {"kind", "requirement_keys", "limitation_refs"}
        if decision_kind == "measure_available":
            exact(
                decision,
                common | {"measure_ref", "purpose"},
                "available measure decision",
            )
            if decision["purpose"] not in {
                "local",
                "acceptance",
                "composition",
                "adequacy",
            }:
                raise ValueError("unknown prerequisite measure purpose")
        elif decision_kind in {"question_resolved", "support_available"}:
            exact(
                decision,
                common
                | {
                    "need_ref",
                    "decision_ref",
                    "target_ref",
                    "state",
                    "policy_strength",
                    "applicability_ref",
                },
                "investigation decision",
            )
            states = (
                {"supported", "refuted"}
                if decision_kind == "question_resolved"
                else {"applicable"}
            )
            if (
                decision["state"] not in states
                or decision["policy_strength"] != "advisory"
            ):
                raise ValueError(
                    "prerequisite finding must retain its limited advisory meaning"
                )
        elif decision_kind == "research_available":
            exact(decision, {"kind", "finding_ref", "role", "state", "requirement_keys",
                             "policy_strength", "limitation_refs"}, "research decision")
            from .investigation import research_resolved

            if not research_resolved(decision["role"], decision["state"]) or decision["policy_strength"] != "advisory":
                raise ValueError("research prerequisite retains its advisory meaning")
        else:
            raise ValueError("unknown prerequisite decision kind")
        names(decision["requirement_keys"], "prerequisite requirements", nonempty=True)
        names(body["fact_keys"], "prerequisite facts", nonempty=True)
        for name, value in decision.items():
            if name.endswith("_ref"):
                Ref.from_record(value)
        for ref in decision["limitation_refs"]:
            Ref.from_record(ref)
    if kind == "measure_proposal":
        if not isinstance(body["components"], Mapping):
            raise ValueError("measure components must map requirements to admitted component evidence")
        for key, reference in body["components"].items():
            names((key,), "component requirement")
            Ref.from_record(reference)
        composite = body["oracle_kind"] == "component_composite"
        names(body["requirement_keys"], "measured requirements", nonempty=not composite)
        if composite and (body["requirement_keys"] or not body["components"]):
            raise ValueError("a component composite names admitted components rather than new checks")
        if body["purpose"] not in {"local", "acceptance", "composition", "adequacy"}:
            raise ValueError("unknown measure purpose")
        if body["oracle_kind"] not in {
            "registered_predicate",
            "independent_execution",
            "checking_program",
            "approved_review",
            "component_composite",
        }:
            raise ValueError("measure requires an explicit grounding route")
        for name in (
            "grounding_refs",
            "positive_control_refs",
            "negative_control_refs",
        ):
            if not composite and not body[name]:
                raise ValueError(
                    "measure proposal must identify grounding and discriminating controls"
                )


@dataclass(frozen=True)
class RefinementRecord:
    kind: str
    campaign_id: OpaqueId
    body: Mapping[str, object]
    producer_ref: Ref
    evidence_refs: tuple[EvidenceRef, ...] = ()
    predecessor_refs: tuple[Ref, ...] = ()
    invocation_id: OpaqueId | None = None
    logical_unit_id: OpaqueId | None = None
    artifact_id: OpaqueId = field(init=False)
    content_hash: Sha256Digest = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.campaign_id, OpaqueId) or not isinstance(
            self.producer_ref, Ref
        ):
            raise ValueError("record requires campaign and producer identities")
        for name in ("invocation_id", "logical_unit_id"):
            if getattr(self, name) is not None and not isinstance(
                getattr(self, name), OpaqueId
            ):
                raise ValueError(f"{name} must be an opaque identity")
        for name, kind in (("evidence_refs", EvidenceRef), ("predecessor_refs", Ref)):
            if not isinstance(getattr(self, name), tuple) or any(
                not isinstance(item, kind) for item in getattr(self, name)
            ):
                raise ValueError(f"{name} must be a typed tuple")
        _validate_body(self.kind, self.body)
        object.__setattr__(self, "body", _freeze_json(self.body, "refinement body"))
        semantic = self.semantic_record()
        object.__setattr__(self, "artifact_id", content_id("refinement", semantic))
        object.__setattr__(self, "content_hash", digest_record(semantic))

    @property
    def ref(self) -> Ref:
        return Ref(self.artifact_id, self.content_hash)

    def semantic_record(self) -> dict:
        return {
            "schema_id": f"openchia.refinement.{self.kind}",
            "schema_version": 1,
            "campaign_id": self.campaign_id.value,
            "invocation_id": self.invocation_id.value if self.invocation_id else None,
            "logical_unit_id": self.logical_unit_id.value
            if self.logical_unit_id
            else None,
            "producer_ref": self.producer_ref.as_record(),
            "evidence_refs": [ref.as_record() for ref in self.evidence_refs],
            "predecessor_refs": [ref.as_record() for ref in self.predecessor_refs],
            "body": _thaw_json(self.body),
        }

    def as_record(self) -> dict:
        return {**self.ref.as_record(), **self.semantic_record()}

    @classmethod
    def from_record(cls, value: object) -> RefinementRecord:
        row = exact(
            value,
            {
                "schema_id",
                "schema_version",
                "artifact_id",
                "content_hash",
                "campaign_id",
                "invocation_id",
                "logical_unit_id",
                "producer_ref",
                "evidence_refs",
                "predecessor_refs",
                "body",
            },
            "refinement envelope",
        )
        if type(row["schema_version"]) is not int or row["schema_version"] != 1:
            raise ValueError("unsupported refinement schema version")
        prefix = "openchia.refinement."
        if not isinstance(row["schema_id"], str) or not row["schema_id"].startswith(
            prefix
        ):
            raise ValueError("unregistered refinement schema")
        result = cls(
            row["schema_id"][len(prefix) :],
            OpaqueId(row["campaign_id"]),
            row["body"],
            Ref.from_record(row["producer_ref"]),
            tuple(EvidenceRef.from_record(ref) for ref in row["evidence_refs"]),
            tuple(Ref.from_record(ref) for ref in row["predecessor_refs"]),
            OpaqueId(row["invocation_id"])
            if row["invocation_id"] is not None
            else None,
            OpaqueId(row["logical_unit_id"])
            if row["logical_unit_id"] is not None
            else None,
        )
        if result.ref != Ref.from_record({
            key: row[key] for key in ("artifact_id", "content_hash")
        }):
            raise ValueError("refinement record content identity mismatch")
        return result
