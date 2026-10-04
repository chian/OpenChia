"""Call authority belongs to the exact approved workflow, not parent pointers.

These are serialization/approval invariants, not executable-function admission.
"""

from dataclasses import replace

import pytest

from agent.duet_contracts import DuetIdentity, DuetPolicy, digest_record, content_id
from agent.duet_service import DuetService
from agent.duet_store import DuetStore
from agent.episode_blueprints import (
    workflow_blueprint_from_spec,
    workflow_spec_from_blueprint,
)
from agent.episode_call_contracts import EpisodeRepeatableCallSpec
from agent.episode_contracts import (
    EpisodeCreationSpec,
    EpisodeDesignSpec,
    EpisodeFunctionSelectionSpec,
    EpisodeNumericalControlSpec,
    EpisodeWorkflowSpec,
    OpaqueId,
    Sha256Digest,
)
from handoff_library import ADMIT_PARENT_REQUEST, ADMIT_CHILD_RESULT
from numeric_control_library import PAIRED_INCIDENCE, PREDICTED_CREDIT_UPPER_BOUND


def selected(function, arguments=None):
    return EpisodeFunctionSelectionSpec(
        function.library,
        function.function_id,
        function.interface,
        function.definition_id,
        arguments or {},
    )


def workflow():
    numerical = EpisodeNumericalControlSpec(
        selected(PAIRED_INCIDENCE, {"uncertainty_alpha": 0.05}),
        selected(
            PREDICTED_CREDIT_UPPER_BOUND, {"max_predicted_marginal_hypervolume": 0.01}
        ),
    )
    return EpisodeWorkflowSpec((
        EpisodeDesignSpec(
            "parts",
            None,
            EpisodeCreationSpec(
                goal="Refine approved behavioral slices.",
                progress="Admitted state transitions.",
                stopping="Frozen numerical continuation.",
                numeric_control=numerical,
            ),
        ),
    ))


def call():
    request = selected(ADMIT_PARENT_REQUEST)
    return EpisodeRepeatableCallSpec(
        "parts",
        "nested_parts",
        "parts",
        request,
        selected(ADMIT_CHILD_RESULT),
        request,
        request,
        request,
    )


def test_legacy_encoding_and_exact_approval_include_repeatable_call_authority(tmp_path):
    old = workflow()
    assert set(old.as_record()) == {"episodes"}
    assert EpisodeWorkflowSpec.from_record(old.as_record()) == old
    extended = replace(old, repeatable_calls=(call(),))
    assert extended.workflow_hash != old.workflow_hash
    blueprint = workflow_blueprint_from_spec(extended)
    assert workflow_spec_from_blueprint(blueprint) == extended
    assert EpisodeWorkflowSpec.from_json(extended.to_json()) == extended

    store = DuetStore(tmp_path / "duet.db")
    try:
        service = DuetService(store, allowed_episode_capabilities=())
        policy = DuetPolicy(content_id("policy", "calls"))
        identity = DuetIdentity(
            content_id("duet", "calls"),
            content_id("human", "calls"),
            policy.policy_id,
            content_id("conversation", "calls"),
        )
        service.open_duet(identity, policy)
        draft = service.record_initial_workflow_draft(
            duet_id=identity.duet_id,
            workflow_blueprint=blueprint,
            expected_draft_artifact_id=None,
            expected_draft_hash=None,
            expected_draft_revision=None,
            source_stage="human_edit",
        )
        authority = service.approve_current_workflow(
            identity,
            source_draft_artifact_id=OpaqueId(draft["artifact_id"]),
            source_draft_hash=Sha256Digest(draft["content_hash"]),
        )
        artifact = store.get_artifact(authority.authority_approval.artifact_id.value)
        assert (
            digest_record(artifact["record"]["workflow"])
            == authority.workflow_approval.content_hash
        )
        assert (
            artifact["record"]["workflow"]["repeatable_calls"]
            == extended.as_record()["repeatable_calls"]
        )
        changed = replace(
            extended, repeatable_calls=(replace(call(), slot_name="different_slot"),)
        )
        assert changed.workflow_hash != extended.workflow_hash
    finally:
        store.close()


def test_call_bindings_do_not_relax_tree_or_template_validation():
    with pytest.raises(ValueError, match="outside the approved workflow"):
        replace(
            workflow(),
            repeatable_calls=(replace(call(), callee_template_local_id="invented"),),
        )
    with pytest.raises(ValueError, match="unique"):
        replace(workflow(), repeatable_calls=(call(), call()))
    with pytest.raises(ValueError, match="own workflow parent"):
        replace(
            workflow(),
            episodes=(
                replace(workflow().episodes[0], workflow_parent_local_id="parts"),
            ),
            repeatable_calls=(call(),),
        )
    malformed = {
        **workflow().as_record(),
        "repeatable_calls": {"version": True, "bindings": [call().as_record()]},
    }
    with pytest.raises(ValueError, match="unsupported"):
        EpisodeWorkflowSpec.from_record(malformed)
