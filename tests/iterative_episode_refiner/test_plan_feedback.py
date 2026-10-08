"""Rejected plan feedback must identify the correction, not change the criteria."""

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ("missing", "unexpected"))
async def test_plan_feedback_identifies_exact_mapping_difference(campaign, mismatch):
    designer = campaign.designer()
    required = set(designer.body["contribution_requirement_keys"])
    mapping = {key: "Implement this assigned requirement" for key in required}
    omitted = sorted(required)[0]
    extra = "preservation_only_requirement"
    if mismatch == "missing":
        del mapping[omitted]
    else:
        mapping[extra] = "Retain this separate preservation condition"

    def plan(requirements):
        return campaign.record(
            "design_plan",
            {
                "assignment_ref": designer.ref.as_record(),
                "approach_key": "implement the assigned contribution",
                "requirement_mapping": requirements,
                "assumption_refs": [],
                "proposed_component_refs": [],
                "intended_change_scope": [campaign.source_path],
                "intended_materialization_targets": [],
                "dependency_effects": {},
                "local_measure_ref": designer.body["local_measure_ref"],
                "acceptance_measure_ref": designer.body["acceptance_measure_ref"],
                "preservation_measure_refs": [],
                "expected_observation_refs": [],
                "falsifying_observation_refs": [],
                "open_need_refs": [],
            },
        )

    original = campaign.candidate.ref
    with pytest.raises(ValueError) as error:
        campaign.perform("admit_plan", {"plan": plan(mapping).as_record()})
    assert f"missing={repr([omitted] if mismatch == 'missing' else [])}" in str(error.value)
    assert f"unexpected={repr([extra] if mismatch == 'unexpected' else [])}" in str(error.value)
    assert not campaign.entries("plan")
    assert campaign.candidate.ref == original

    corrected = plan({key: "Implement this assigned requirement" for key in required})
    campaign.perform("admit_plan", {"plan": corrected.as_record()})
    assert [entry.record.ref for entry in campaign.entries("plan")] == [corrected.ref]
    assert campaign.candidate.ref == original
    assert not campaign.entries("unit")  # Admission alone has not earned credit.
