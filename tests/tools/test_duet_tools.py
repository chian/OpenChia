import json
from types import SimpleNamespace

from agent.episode_contracts import OpaqueId, Sha256Digest
from agent.inline_tool_executors import INLINE_TOOL_EXECUTORS, InlineToolContext


def test_episode_progress_accepts_registered_evidence_not_model_scores():
    agent = SimpleNamespace(
        _active_episode_id="episode_" + "a" * 64,
        _active_episode_evidence_ids=frozenset({"evidence_" + "b" * 64}),
        _episode_progress_reports=[],
    )
    context = InlineToolContext(effective_task_id="task")

    rejected_score = json.loads(
        INLINE_TOOL_EXECUTORS["episode_progress"](
            agent, {"value": 0.99}, context
        )
    )
    accepted_evidence = json.loads(
        INLINE_TOOL_EXECUTORS["episode_progress"](
            agent,
            {"accepted_evidence_ids": ["evidence_" + "b" * 64]},
            context,
        )
    )
    rejected_unknown = json.loads(
        INLINE_TOOL_EXECUTORS["episode_progress"](
            agent,
            {"accepted_evidence_ids": ["evidence_" + "c" * 64]},
            context,
        )
    )

    assert rejected_score == {"accepted": False, "reason": "invalid_evidence_ids"}
    assert accepted_evidence["accepted"] is True
    assert accepted_evidence["accepted_count"] == 1
    assert rejected_unknown["reason"] == "unregistered_evidence"


def test_duet_protocol_tools_are_agent_bound_and_delegate_is_absent():
    expected = {
        "duet_contract_patch",
        "duet_status",
        "episode_workflow_read",
        "episode_workflow_update",
        "duet_answer",
        "duet_decision",
        "creator_context_artifact",
        "creator_context_read",
        "openchia_scope",
        "creator_log_read",
        "workflow_candidate",
        "episode_progress",
    }
    assert expected <= set(INLINE_TOOL_EXECUTORS)
    assert {
        "duet_contract_review",
        "workflow_review",
        "episode_creator",
    }.isdisjoint(INLINE_TOOL_EXECUTORS)
    assert "delegate_task" not in INLINE_TOOL_EXECUTORS


def test_openchia_scope_returns_exact_host_derived_role_boundaries():
    context = InlineToolContext(effective_task_id="scope")
    duet = SimpleNamespace(
        _openchia_authority_scope={
            "schema_version": 1,
            "role": "duet",
            "callable_tool_names": ["duet_status", "openchia_scope"],
            "assignable_child_capability_names": ["web_search"],
        }
    )
    creator = SimpleNamespace(
        _openchia_authority_scope={
            "schema_version": 1,
            "role": "creator",
            "callable_tool_names": ["openchia_scope", "workflow_candidate"],
            "assignable_child_capability_names": ["terminal"],
            "may_create_child_creators": False,
        }
    )

    duet_scope = json.loads(
        INLINE_TOOL_EXECUTORS["openchia_scope"](duet, {}, context)
    )
    creator_scope = json.loads(
        INLINE_TOOL_EXECUTORS["openchia_scope"](creator, {}, context)
    )

    assert duet_scope["accepted"] is True
    assert duet_scope["scope"]["role"] == "duet"
    assert duet_scope["scope"]["callable_tool_names"] != duet_scope["scope"][
        "assignable_child_capability_names"
    ]
    assert creator_scope["scope"]["role"] == "creator"
    assert creator_scope["scope"]["may_create_child_creators"] is False


def test_openchia_scope_fails_closed_without_host_binding():
    result = json.loads(
        INLINE_TOOL_EXECUTORS["openchia_scope"](
            SimpleNamespace(),
            {},
            InlineToolContext(effective_task_id="scope"),
        )
    )

    assert result == {
        "accepted": False,
        "reason": "no_host_bound_openchia_scope",
    }


def test_episode_workflow_update_persists_without_review_or_execution():
    calls = []

    agent = SimpleNamespace(
        _duet_workflow_updater=lambda workflow, **kwargs: (
            calls.append((workflow, kwargs))
            or {
                "revision": 1,
                "artifact_id": "artifact_" + "a" * 64,
                "content_hash": "sha256:" + "1" * 64,
                "ready": True,
                "validation_deficits": [],
            }
        )
    )
    workflow = {"episodes": []}
    result = json.loads(
        INLINE_TOOL_EXECUTORS["episode_workflow_update"](
            agent,
            {"workflow": workflow, "expected_workflow_hash": None},
            InlineToolContext(effective_task_id="duet"),
        )
    )
    assert result["accepted"] is True
    assert calls == [
        (
            workflow,
            {"expected_workflow_hash": None, "source_stage": "duet"},
        )
    ]


def test_workflow_candidate_preserves_validation_message_and_activity():
    activity = []
    workflow = {"episodes": []}

    def reject(_workflow):
        raise ValueError("episodes[2].contract.result_schema is required")

    agent = SimpleNamespace(
        _creator_workflow_submit=reject,
        _creator_required_context_ids=frozenset(),
        _creator_context_read_ids=set(),
        _creator_reviewed_workflow_hashes={
            Sha256Digest.of_record(workflow).value
        },
        _creator_activity_publisher=lambda stage, code, details: activity.append(
            (stage, code, details)
        ),
    )

    result = json.loads(
        INLINE_TOOL_EXECUTORS["workflow_candidate"](
            agent,
            {"workflow": workflow},
            InlineToolContext(effective_task_id="creator"),
        )
    )

    assert result == {
        "accepted": False,
        "reason": "ValueError",
        "message": "episodes[2].contract.result_schema is required",
    }
    assert agent._creator_last_candidate_result == result
    assert [item[:2] for item in activity] == [
        ("submitting", "workflow_candidate_submitting"),
        ("revising", "workflow_candidate_rejected"),
    ]


def test_workflow_candidate_does_not_require_a_semantic_review():
    submitted = []
    drafts = []
    workflow = {"episodes": []}

    def submit(value):
        submitted.append(value)
        return SimpleNamespace(
            artifact_id=OpaqueId.mint("design", "candidate"),
            revision=1,
            workflow=SimpleNamespace(
                workflow_hash=Sha256Digest.of_record(value),
                episodes=(),
            ),
        )

    agent = SimpleNamespace(
        _creator_workflow_submit=submit,
        _creator_workflow_draft_recorder=(
            lambda value, stage: drafts.append((value, stage))
        ),
        _creator_required_context_ids=frozenset(),
        _creator_context_read_ids=set(),
    )

    result = json.loads(
        INLINE_TOOL_EXECUTORS["workflow_candidate"](
            agent,
            {"workflow": workflow},
            InlineToolContext(effective_task_id="creator"),
        )
    )

    assert result["accepted"] is True
    assert result["shadow_reviewed"] is False
    assert submitted == [workflow]
    assert drafts == [(workflow, "candidate")]


def test_required_context_is_delivered_exactly_before_workflow_candidate():
    artifact_id = OpaqueId.mint("context", "required-context").value
    content = {
        "interface": {
            "inputs": ["artifact_id", "content_hash"],
            "outputs": ["evidence_id"],
        }
    }
    calls = []

    def submit(workflow):
        calls.append(workflow)
        return SimpleNamespace(
            artifact_id=OpaqueId.mint("design", "with-context"),
            revision=1,
            workflow=SimpleNamespace(
                workflow_hash=Sha256Digest.of_record(workflow),
                episodes=(),
            ),
        )

    agent = SimpleNamespace(
        _creator_workflow_submit=submit,
        _creator_context_artifacts={
            artifact_id: {
                "reference": {
                    "artifact_id": artifact_id,
                    "content_hash": "sha256:" + "1" * 64,
                    "artifact_kind": "interface_contract",
                    "schema_version": 1,
                    "purpose": "handoff_contract",
                    "required": True,
                },
                "content": content,
            }
        },
        _creator_required_context_ids=frozenset({artifact_id}),
        _creator_context_read_ids=set(),
    )
    context = InlineToolContext(effective_task_id="creator")
    blocked = json.loads(
        INLINE_TOOL_EXECUTORS["workflow_candidate"](
            agent,
            {"workflow": {"episodes": []}},
            context,
        )
    )
    assert blocked == {
        "accepted": False,
        "reason": "required_context_unread",
        "artifact_ids": [artifact_id],
    }

    delivered = json.loads(
        INLINE_TOOL_EXECUTORS["creator_context_read"](
            agent,
            {"artifact_id": artifact_id},
            context,
        )
    )
    assert delivered["delivery"] == "exact_whole_artifact_v1"
    assert delivered["content"] == content

    accepted = json.loads(
        INLINE_TOOL_EXECUTORS["workflow_candidate"](
            agent,
            {"workflow": {"episodes": []}},
            context,
        )
    )
    assert accepted["accepted"] is True
    assert len(calls) == 1
