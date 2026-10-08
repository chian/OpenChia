"""State tests use the same genuinely admitted target/refiner campaign fixture.

Builder replies are supplied; materialization and campaign admission are real.
These tests exercise durable state/control, not model reasoning or confinement.
"""

import pytest_asyncio

from agent.duet_contracts import content_id
from function_library.refinement_contract import CHILDREN, ROLE_SPECIALIZATION
from iterative_episode_refiner.campaign_store import CampaignView
from iterative_episode_refiner.records import RefinementRecord
from iterative_episode_refiner.state_machine import judgment_lineage
from tests.episode_runtime.conftest import claim_store
from tests.episode_runtime.testing_harness.refinement_fixture import prepared_refiner


def pytest_addoption(parser):
    parser.addoption("--live-coding-profile", default=None,
                     help="Opt in to reading this profile's Codex credential for a live coding check (no profile writes)")
    parser.addoption("--live-coding-binding", default=None,
                     help="Exact saved Duet model-binding artifact to use for the live coding check")


class CampaignFixture:
    def __init__(self, session):
        self.session = session
        self.store = session.store
        self.duets = self.store.evidence.duets
        self.builds = self.store.evidence.builds
        self.campaign_id = session.campaign_id
        self.producer = session.contract.producer_ref
        root = session.calls[session.root_id]
        self.root_invocation = root.invocation_id
        self.current_invocation = root.invocation_id
        self.root_assignment = root.assignment
        self.current_assignment = root.assignment
        self.unit = content_id("state_test_unit", "initial")
        self.counter = 0
        self.initial = self.candidate
        self.source_path = next(iter(self.initial.body["files"]))
        self.initial_source = self.builds.read_blob(self.initial.body["files"][self.source_path])
        self.requirements = sorted({
            row.record.body["requirement_key"] for row in self.entries("check")
            if row.record.body["evidence_kind"] == "execution"
        })
        assert len(self.requirements) == 2

    def record(self, kind, body, **kwargs):
        return RefinementRecord(kind, self.campaign_id, body, self.producer, **kwargs)

    def assignment(self, role, parent):
        from iterative_episode_refiner.records import Ref
        from iterative_episode_refiner.report_contract import requirement_address, requirement_catalog

        with self.session.view() as view:
            returned = view.data(Ref.from_record(parent.body["return_projection_ref"]))
            catalog = requirement_catalog(view)
        addresses = {requirement_address(catalog[key]) for key in self.requirements}
        return_ref = self.store.put_data(self.session.duet_id, "fixture_return", {
            **returned, "measurements": [
                {**item, "requirements": [address for address in item["requirements"] if address in addresses]}
                for item in returned["measurements"] if addresses.intersection(item["requirements"])
            ],
        })
        body = {
            **parent.as_record()["body"],
            "return_projection_ref": return_ref.as_record(),
            "parent_assignment_ref": parent.ref.as_record(),
            "coordinating_invocation_id": self.current_invocation.value,
            "role": role,
            "materialization_targets": list(parent.body["materialization_targets"]) if ROLE_SPECIALIZATION[role] == "materialization_implementer" else [],
            "writable_paths": list(parent.body["writable_paths"]) if ROLE_SPECIALIZATION[role] == "implementer" else [],
            "scope_requirement_keys": self.requirements,
            "contribution_requirement_keys": self.requirements,
            "preservation_requirement_keys": [],
            "baseline_candidate_ref": self.candidate.ref.as_record(),
            "allowed_child_bindings": list(CHILDREN[role]),
            "supersedes_assignment_refs": [],
        }
        body["judgment_lineage"] = judgment_lineage(body)
        return self.record("assignment", body)

    def attempt(self, action, payload):
        self.counter += 1
        return self.record(
            "attempt",
            {
                "operation_id": content_id("state_test_operation", {
                    "campaign_id": self.campaign_id.value, "ordinal": self.counter,
                }).value,
                "invocation_id": self.current_invocation.value,
                "logical_unit_id": self.unit.value,
                "action": action,
                "payload": payload,
            },
            invocation_id=self.current_invocation,
            logical_unit_id=self.unit,
        )

    def perform(self, action, payload):
        return self.store.commit_attempt(self.attempt(action, payload))

    def entries(self, collection):
        with self.duets.transaction() as connection:
            return CampaignView(connection, self.campaign_id).entries(collection)

    @property
    def candidate(self):
        with self.duets.transaction() as connection:
            return CampaignView(connection, self.campaign_id).candidate

    def enter(self, role):
        invocation = content_id("state_test_invocation", {"role": role, "ordinal": self.counter})
        assignment = self.assignment(role, self.current_assignment)
        self.perform("assign", {"assignment": assignment.as_record(), "invocation_id": invocation.value})
        self.perform("enter_child", {"invocation_id": invocation.value})
        self.current_assignment = assignment
        self.current_invocation = invocation
        self.unit = content_id("state_test_unit", invocation.value)
        return assignment

    def designer(self):
        return self.root_assignment

    def implementer(self, *, additional_paths=()):
        designer = self.designer()
        self.plan = self.record(
            "design_plan",
            {
                "assignment_ref": designer.ref.as_record(),
                "approach_key": "preserve both independently assigned properties",
                "requirement_mapping": {key: "Preserve the independently checked property" for key in designer.body["contribution_requirement_keys"]},
                "assumption_refs": [],
                "proposed_component_refs": [],
                "intended_change_scope": [self.source_path, *additional_paths],
                "intended_materialization_targets": [],
                "dependency_effects": [],
                "local_measure_ref": designer.body["local_measure_ref"],
                "acceptance_measure_ref": designer.body["acceptance_measure_ref"],
                "preservation_measure_refs": [],
                "expected_observation_refs": [],
                "falsifying_observation_refs": [],
                "open_need_refs": [],
            },
        )
        self.perform("admit_plan", {"plan": self.plan.as_record()})
        self.implementation = self.enter("implementer")
        return self.implementation

    def change(self, source, *, before=None):
        before = before or self.candidate
        change = self.record(
            "change",
            {
                "assignment_ref": self.implementation.ref.as_record(),
                "design_plan_ref": self.plan.ref.as_record(),
                "expected_head_ref": before.ref.as_record(),
                "file_operations": [{
                    "kind": "replace", "logical_path": self.source_path,
                    "before_hash": before.body["files"][self.source_path],
                    "after_blob_hash": self.builds.put_blob(source).value,
                }],
                "implementation_detail_operations": [],
                "findings": [],
                "rationale_claim_refs": [],
            },
        )
        return self.attempt("apply_change", {"change": change.as_record()})


@pytest_asyncio.fixture
async def campaign(tmp_path):
    # Existing inert executor identity only; no candidate execution is claimed.
    runtime_identity = claim_store(tmp_path / "identity")[1].runtime_identity
    checks = [
        {
            "requirement_field": field,
            "expected": True,
            "observation_path": f"/payload/typed_status/{field}",
            "grounding": {"fixture": "unmeasured state/control invariants", "field": field},
        }
        for field in ("goal", "progress")
    ]
    async with prepared_refiner(
        tmp_path, runtime_identity, runtime_checks=checks, allow_source_edits=True,
    ) as session:
        yield CampaignFixture(session)
