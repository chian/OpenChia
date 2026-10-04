"""Bind the fixed refiner to the target's existing human build authority.

This is host authorization of an implementation tool, not a fabricated second
human decision or permission for a worker to create arbitrary Episodes.
"""

from agent.duet_contracts import DuetIdentity, content_id
from agent.episode_blueprints import workflow_blueprint_from_spec
from agent.episode_contracts import OpaqueId, Sha256Digest
from episode_builder._contract_chain import ApprovedBuildRequest
from iterative_episode_refiner.design import refinement_workflow_spec


def authorize_program(host, target_request):
    parent = host.service.resolve_current_build_authorization(host.identity.duet_id)
    if parent.authority_approval != target_request.authority_approval:
        raise ValueError("build authority changed before refinement")
    workflow = refinement_workflow_spec()
    identity = DuetIdentity(
        duet_id=content_id(
            "duet",
            {
                "build_refiner_for": parent.authority_approval.approval_id.value,
                "workflow_hash": workflow.workflow_hash.value,
            },
        ),
        human_authority_id=host.identity.human_authority_id,
        policy_id=host.policy.policy_id,
        conversation_id=host.identity.conversation_id,
    )
    host.service.open_duet(identity, host.policy)
    row = host.store.get_duet(identity.duet_id.value)
    if row["authority_head_approval_id"] is None:
        prior = host.store.latest_artifact(
            duet_id=identity.duet_id.value, kind="episode_workflow_draft"
        )
        draft = host.service.record_initial_workflow_draft(
            duet_id=identity.duet_id,
            workflow_blueprint=workflow_blueprint_from_spec(workflow),
            expected_draft_artifact_id=None if prior is None else prior["artifact_id"],
            expected_draft_hash=None if prior is None else prior["content_hash"],
            expected_draft_revision=None if prior is None else prior["revision"],
            source_stage="build_refiner",
        )
        authorization = host.service._seal_workflow(
            identity,
            source_draft_artifact_id=OpaqueId(draft["artifact_id"]),
            source_draft_hash=Sha256Digest(draft["content_hash"]),
            build_refiner_parent=parent.authority_approval,
        )
    else:
        authorization = host.service.resolve_current_build_authorization(
            identity.duet_id
        )
        if authorization.frozen_workflow.workflow != workflow:
            raise ValueError("stored build refiner differs from the registered program")
    return ApprovedBuildRequest(
        authority_approval=authorization.authority_approval,
        workflow_approval=authorization.workflow_approval,
        frozen_workflow=authorization.frozen_workflow,
        admission_authority=authorization.admission_authority,
        request_nonce=target_request.build_request_id.value,
    )
