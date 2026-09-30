from __future__ import annotations

import pytest

from agent.episode_blueprints import (
    EPISODE_CREATION_BLUEPRINT_SCHEMA,
    creation_blueprint_from_spec,
    creation_spec_from_blueprint,
    workflow_blueprint_from_spec,
    workflow_spec_from_blueprint,
)
from agent.episode_contracts import (
    CREATOR_METHOD_CREDIT_PROGRESS_ADAPTER,
    DURABLE_EVIDENCE_PROGRESS_ADAPTER,
    EpisodeCreationSpec,
    EpisodeDesignSpec,
    EpisodeWorkflowSpec,
    NumericProgressMeasure,
    OpaqueId,
    ProgressDirection,
    ProgressStopCriteria,
    TERMINAL_RESULT_PROGRESS_ADAPTER,
)


def _spec() -> EpisodeCreationSpec:
    return EpisodeCreationSpec(
        goal="Collect one accepted observation.",
        progress=NumericProgressMeasure(
            metric_id=OpaqueId.mint("metric", "internal-only"),
            description="Accepted observations",
            unit="observations",
            direction=ProgressDirection.INCREASE,
            baseline=0,
        ),
        stopping=ProgressStopCriteria(
            target=1,
            minimum_delta=1,
            stagnation_observations=2,
        ),
        execution_capability_names=("web_search",),
    )


def test_blueprint_round_trip_mints_internal_identity_and_authority_fields():
    internal = _spec()
    blueprint = creation_blueprint_from_spec(internal)

    assert "metric_id" not in blueprint["progress"]
    assert "schema_version" not in blueprint
    assert "can_create_episodes" not in blueprint
    assert "capability_inheritance" not in blueprint

    restored = creation_spec_from_blueprint(
        blueprint,
        identity_namespace="test:root",
    )
    assert restored.goal == internal.goal
    assert restored.progress.metric_id != internal.progress.metric_id
    assert restored.progress.metric_id == creation_spec_from_blueprint(
        blueprint,
        identity_namespace="test:root",
    ).progress.metric_id
    assert restored.can_create_episodes is False

    workflow = EpisodeWorkflowSpec(
        (EpisodeDesignSpec("root", None, internal),)
    )
    translated = workflow_spec_from_blueprint(
        workflow_blueprint_from_spec(workflow),
        identity_namespace="workflow-test",
    )
    assert translated.episodes[0].local_id == "root"
    assert translated.episodes[0].contract.goal == internal.goal


def test_blueprint_rejects_model_claims_to_host_owned_fields():
    blueprint = creation_blueprint_from_spec(_spec())
    blueprint["can_create_episodes"] = True
    blueprint["progress"]["metric_id"] = OpaqueId.mint(
        "metric", "model-claim"
    ).value

    with pytest.raises(ValueError, match="unknown"):
        creation_spec_from_blueprint(
            blueprint,
            identity_namespace="test:smuggled-authority",
        )


def test_blueprint_exposes_only_registered_progress_adapters():
    adapter_schema = EPISODE_CREATION_BLUEPRINT_SCHEMA["properties"]["progress"][
        "properties"
    ]["adapter_id"]

    assert set(adapter_schema["enum"]) == {
        CREATOR_METHOD_CREDIT_PROGRESS_ADAPTER,
        DURABLE_EVIDENCE_PROGRESS_ADAPTER,
        TERMINAL_RESULT_PROGRESS_ADAPTER,
    }
