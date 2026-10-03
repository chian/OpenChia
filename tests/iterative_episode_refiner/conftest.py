"""Real transactional stores with inert approval/executor facts for state tests.

These fixtures establish storage/control behavior, not confinement or reasoning.
The actual executor transport has a separate acceptance requirement.
"""

from dataclasses import replace

import pytest

from agent.duet_contracts import (
    DuetIdentity,
    DuetPolicy,
    content_id,
    digest_record,
)
from agent.duet_service import DuetService
from agent.duet_store import DuetStore
from agent.episode_blueprints import workflow_blueprint_from_spec
from agent.episode_contracts import (
    EpisodeCreationSpec,
    EpisodeDesignSpec,
    EpisodeWorkflowSpec,
    EpisodeFunctionSelectionSpec,
    EpisodeNumericalControlSpec,
    OpaqueId,
    Sha256Digest,
)
from episode_builder.store import BuildStore
from episode_runtime.store import RunStore
from function_library.refinement_checks import EXACT_VALUE
from function_library.refinement_control import SEMANTIC_YIELD, BOUNDED_RAREFACTION
from iterative_episode_refiner.campaign_store import CampaignStore, CampaignView
from iterative_episode_refiner.evidence import EvidenceReader
from iterative_episode_refiner.records import Ref, RefinementRecord
from iterative_episode_refiner.state_machine import judgment_lineage
from numeric_control_library import PAIRED_INCIDENCE, PREDICTED_CREDIT_UPPER_BOUND


def oid(kind, value="fixture"):
    return content_id(kind, value)


def numeric_control():
    def selected(function, arguments):
        return EpisodeFunctionSelectionSpec(
            function.library,
            function.function_id,
            function.interface,
            function.definition_id,
            arguments,
        )

    return EpisodeNumericalControlSpec(
        selected(PAIRED_INCIDENCE, {"uncertainty_alpha": 0.05}),
        selected(
            PREDICTED_CREDIT_UPPER_BOUND, {"max_predicted_marginal_hypervolume": 0.01}
        ),
    )


class CampaignFixture:
    def __init__(self, root, *, independent_checks=False):
        self.root = root
        self.independent_checks = independent_checks
        self.duets = DuetStore(root / "duet.db")
        self.builds = BuildStore(root)
        self.runs = RunStore(root / "runs")
        self.campaign_id = oid("campaign")
        self.duet_id = oid("duet")
        self.root_invocation = oid("invocation", "root")
        self.unit = oid("unit", "initial")
        self.counter = 0
        service = DuetService(self.duets, allowed_episode_capabilities=())
        policy = DuetPolicy(oid("policy"))
        identity = DuetIdentity(
            self.duet_id, oid("human"), policy.policy_id, oid("conversation")
        )
        service.open_duet(identity, policy)
        workflow = EpisodeWorkflowSpec((
            EpisodeDesignSpec(
                "target",
                None,
                EpisodeCreationSpec(
                    goal="Preserve first occurrence order while removing duplicate strings.",
                    progress="Independently demonstrated correct results.",
                    stopping="Registered numerical continuation.",
                    numeric_control=numeric_control(),
                ),
            ),
        ))
        draft = service.record_initial_workflow_draft(
            duet_id=self.duet_id,
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
        self.approval = Ref(
            authorization.authority_approval.approval_id,
            digest_record(authorization.authority_approval.as_record()),
        )
        self.producer = self.raw("host", {"kind": "state_test_host"})
        self.environment = self.raw(
            "environment", {"python": "fixture", "inputs": "fixed"}
        )
        self.measure = self.raw(
            "measure",
            {
                "purpose": "local",
                "requires": ["ordered", "unique"],
                "independent_order": independent_checks,
            },
        )
        self.acceptance = self.raw("acceptance", {"purpose": "independent acceptance"})
        self.composition = self.raw("composition", {"purpose": "enclosing composition"})
        self.harness = Ref(oid("manifest"), digest_record({"harness": "inert test"}))
        self.selection = self.raw(
            "predicate",
            {
                key: EXACT_VALUE.bind("check").as_record()[key]
                for key in (
                    "library",
                    "function_id",
                    "interface",
                    "definition_id",
                    "arguments",
                )
            },
        )
        self.initial = self.record(
            "candidate",
            {
                "parent_candidate_ref": None,
                "target_approval_ref": self.approval.as_record(),
                "materialization_ref": self.producer.as_record(),
                "files": {
                    "target.py": self.builds.put_blob(
                        b"def solve(values):\n    return values\n"
                    ).value
                },
                "implementation_directive_refs": [],
                "change_set_ref": None,
                "source_admission_ref": None,
            },
        )
        self.root_assignment = self.assignment("parts", None, self.root_invocation)
        self.checks = tuple(
            self.record(
                "check",
                {
                    "requirement_key": requirement,
                    "origin_refs": [self.producer.as_record()],
                    "measure_ref": self.measure.as_record(),
                    "purpose": "local",
                    "predicate_ref": self.selection.as_record(),
                    "expected": expected,
                    "dependency_paths": ["target.py"],
                    "environment_ref": self.environment.as_record(),
                    "mandatory": True,
                    "guard_keys": [],
                    "grounding_refs": [self.producer.as_record()],
                    "observation_path": f"/payload/typed_status/results/{requirement}",
                },
            )
            for requirement, expected in (("ordered", ["beta", "alpha"]), ("unique", 2))
        )
        self.acceptance_checks = tuple(
            replace(
                check,
                body={
                    **check.body,
                    "purpose": "acceptance",
                    "measure_ref": self.acceptance.as_record(),
                },
            )
            for check in self.checks
        )
        self.composition_checks = tuple(
            replace(
                check,
                body={
                    **check.body,
                    "purpose": "composition",
                    "measure_ref": self.composition.as_record(),
                },
            )
            for check in self.checks
        )
        all_checks = (*self.checks, *self.acceptance_checks, *self.composition_checks)
        policy_ref = self.raw(
            "refiner_policy",
            {
                "root_assignment_ref": self.root_assignment.ref.as_record(),
                "numeric_control": numeric_control().as_record(),
                "yield_function": self.function_selection(SEMANTIC_YIELD),
                "opportunity_function": self.function_selection(BOUNDED_RAREFACTION),
                "check_refs": [check.ref.as_record() for check in all_checks],
                "evaluation_bindings": [
                    {
                        "measure_ref": measure.as_record(),
                        "harness_ref": self.harness.as_record(),
                        "capability_ref": self.producer.as_record(),
                        "purpose": purpose,
                        "input_refs": [],
                    }
                    for measure, purpose in (
                        (self.measure, "local"),
                        (self.acceptance, "acceptance"),
                        (self.composition, "composition"),
                    )
                ],
            },
        )
        self.contract = self.record(
            "campaign",
            {
                "duet_id": self.duet_id.value,
                "target_approval_ref": self.approval.as_record(),
                "target_workflow_ref": self.producer.as_record(),
                "initial_build_receipt_ref": self.producer.as_record(),
                "initial_materialization_ref": self.producer.as_record(),
                "refiner_workflow_approval_ref": self.approval.as_record(),
                "refiner_manifest_ref": self.harness.as_record(),
                "requirement_catalog_ref": self.producer.as_record(),
                "authority_ref": self.producer.as_record(),
                "policy_bundle_ref": policy_ref.as_record(),
                "environment_ref": self.environment.as_record(),
                "guidance_catalog_ref": None,
                "final_projection_ref": self.producer.as_record(),
            },
        )
        self.store = CampaignStore(
            self.duets, EvidenceReader(self.duets, self.builds, self.runs)
        )
        self.store.start(self.contract, self.initial)
        self.current_invocation = self.root_invocation
        self.perform(
            "assign",
            {
                "assignment": self.root_assignment.as_record(),
                "invocation_id": self.root_invocation.value,
            },
        )
        for check in all_checks:
            self.perform("install_check", {"check": check.as_record()})

    def raw(self, kind, body):
        ref = Ref(content_id(kind, body), digest_record(body))
        self.duets.put_artifact(
            artifact_id=ref.artifact_id.value,
            duet_id=self.duet_id.value,
            kind=kind,
            revision=1,
            content_hash=ref.content_hash.value,
            record=body,
        )
        return ref

    @staticmethod
    def function_selection(function):
        return {
            key: function.bind("selection").as_record()[key]
            for key in (
                "library",
                "function_id",
                "interface",
                "definition_id",
                "arguments",
            )
        }

    def record(self, kind, body, **kwargs):
        return RefinementRecord(kind, self.campaign_id, body, self.producer, **kwargs)

    def assignment(
        self,
        role,
        parent,
        invocation,
        *,
        supersedes=(),
        contribution=("ordered", "unique"),
    ):
        body = {
            "parent_assignment_ref": parent.ref.as_record() if parent else None,
            "owning_parts_invocation_id": self.root_invocation.value,
            "role": role,
            "scope_requirement_keys": ["ordered", "unique"],
            "contribution_requirement_keys": list(contribution),
            "scope_partition_ref": self.producer.as_record(),
            "owned_slice_keys": ["order", "duplicates"],
            "baseline_candidate_ref": self.initial.ref.as_record(),
            "goal_record_ref": self.producer.as_record(),
            "authority_ref": self.producer.as_record(),
            "input_refs": [],
            "preservation_requirement_keys": [],
            "dependency_refs": [],
            "local_measure_ref": (
                self.acceptance if role == "verify" else self.measure
            ).as_record(),
            "acceptance_measure_ref": (
                self.composition if role == "parts" else self.acceptance
            ).as_record(),
            "progress_manifest_ref": self.producer.as_record(),
            "allowed_action_classes": [
                "assign",
                "enter_child",
                "return_child",
                "admit_plan",
                "apply_change",
                "install_check",
                "request_evaluation",
                "observe",
                "admit_lesson",
                "close_unit",
                "select_action",
                "coordinate_conflict",
                "resolve_conflict",
            ],
            "allowed_child_bindings": [
                "parts",
                "designer",
                "implementer",
                "verify",
                "question",
                "measure",
                "support",
            ],
            "instruction_refs": [],
            "history_query_ref": self.producer.as_record(),
            "return_projection_ref": self.producer.as_record(),
            "control_bundle_ref": self.producer.as_record(),
            "supersedes_assignment_refs": [item.ref.as_record() for item in supersedes],
            "writable_paths": ["target.py"],
            "protected_paths": ["checks.py"],
            "judgment_lineage": oid("placeholder").value,
        }
        body["judgment_lineage"] = judgment_lineage(body)
        return self.record("assignment", body)

    def attempt(self, action, payload, *, unit=None, evidence=()):
        self.counter += 1
        unit = unit or self.unit
        return self.record(
            "attempt",
            {
                "operation_id": oid("operation", self.counter).value,
                "invocation_id": self.current_invocation.value,
                "logical_unit_id": unit.value,
                "action": action,
                "payload": payload,
            },
            invocation_id=self.current_invocation,
            logical_unit_id=unit,
            evidence_refs=evidence,
        )

    def perform(self, action, payload, **kwargs):
        return self.store.commit_attempt(self.attempt(action, payload, **kwargs))

    def entries(self, collection):
        with self.duets.transaction() as connection:
            return CampaignView(connection, self.campaign_id).entries(collection)

    @property
    def candidate(self):
        with self.duets.transaction() as connection:
            return CampaignView(connection, self.campaign_id).candidate

    def implementer(
        self,
        *,
        contribution=("ordered", "unique"),
        designer=None,
        designer_invocation=None,
    ):
        designer_invocation = designer_invocation or oid("invocation", "designer")
        if designer is None:
            designer = self.assignment(
                "designer", self.root_assignment, designer_invocation
            )
            self.perform(
                "assign",
                {
                    "assignment": designer.as_record(),
                    "invocation_id": designer_invocation.value,
                },
            )
        self.designer, self.designer_invocation = designer, designer_invocation
        self.perform("enter_child", {"invocation_id": designer_invocation.value})
        self.current_invocation = designer_invocation
        self.plan = self.record(
            "design_plan",
            {
                "assignment_ref": designer.ref.as_record(),
                "approach_key": "stable membership filter",
                "requirement_mapping": ["ordered", "unique"],
                "assumption_refs": [],
                "proposed_component_refs": [],
                "intended_change_scope": ["target.py"],
                "dependency_effects": [],
                "local_measure_ref": self.measure.as_record(),
                "acceptance_measure_ref": self.acceptance.as_record(),
                "preservation_measure_refs": [],
                "expected_observation_refs": [],
                "falsifying_observation_refs": [],
                "open_need_refs": [],
            },
        )
        self.perform("admit_plan", {"plan": self.plan.as_record()})
        invocation = oid("invocation", f"implementer-{self.counter}")
        self.implementation = self.assignment(
            "implementer", designer, invocation, contribution=contribution
        )
        self.perform(
            "assign",
            {
                "assignment": self.implementation.as_record(),
                "invocation_id": invocation.value,
            },
        )
        self.perform("enter_child", {"invocation_id": invocation.value})
        self.current_invocation = invocation
        return self.implementation

    def reassign_implementation(self, *, contribution=("ordered", "unique")):
        previous = self.implementation
        self.perform("return_child", {})
        self.current_invocation = self.designer_invocation
        self.unit = oid("unit", f"successor-{self.counter}")
        invocation = oid("invocation", f"successor-{self.counter}")
        self.implementation = self.assignment(
            "implementer",
            self.designer,
            invocation,
            supersedes=(previous,),
            contribution=contribution,
        )
        self.perform(
            "assign",
            {
                "assignment": self.implementation.as_record(),
                "invocation_id": invocation.value,
            },
        )
        self.perform("enter_child", {"invocation_id": invocation.value})
        self.current_invocation = invocation

    def change(self, source, *, before=None):
        before = before or self.candidate
        change = self.record(
            "change",
            {
                "assignment_ref": self.implementation.ref.as_record(),
                "design_plan_ref": self.plan.ref.as_record(),
                "expected_head_ref": before.ref.as_record(),
                "file_operations": [
                    {
                        "kind": "replace",
                        "logical_path": "target.py",
                        "before_hash": before.body["files"]["target.py"],
                        "after_blob_hash": self.builds.put_blob(source).value,
                    }
                ],
                "implementation_detail_operations": [],
                "rationale_claim_refs": [],
            },
        )
        return self.attempt("apply_change", {"change": change.as_record()})


@pytest.fixture
def campaign(tmp_path):
    fixture = CampaignFixture(tmp_path)
    yield fixture
    fixture.duets.close()
