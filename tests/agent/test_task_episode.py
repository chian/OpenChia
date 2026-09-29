from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.episode_contracts import (
    DURABLE_EVIDENCE_PROGRESS_ADAPTER,
    TERMINAL_RESULT_PROGRESS_ADAPTER,
    ChildEpisodePhase,
    EpisodeCreationSpec,
    NumericProgressMeasure,
    OpaqueId,
    ProgressDirection,
    ProgressStopCriteria,
)
from agent.task_episode import (
    TaskEpisodeController,
    TaskIterationAction,
    TaskIterationObservation,
    hermes_iteration_source,
)


def _spec(adapter_id: str, *, stagnation: int = 3) -> EpisodeCreationSpec:
    return EpisodeCreationSpec(
        goal="Produce one host-persisted result.",
        progress=NumericProgressMeasure(
            metric_id=OpaqueId.mint("metric", adapter_id),
            description="Host-accepted progress",
            unit="accepted results",
            direction=ProgressDirection.INCREASE,
            baseline=0,
            adapter_id=adapter_id,
        ),
        stopping=ProgressStopCriteria(
            target=1,
            minimum_delta=1,
            stagnation_observations=stagnation,
        ),
    )


def test_task_success_requires_measured_progress_and_a_persisted_result():
    controller = TaskEpisodeController(
        _spec(DURABLE_EVIDENCE_PROGRESS_ADAPTER)
    )
    evidence_id = OpaqueId.mint("evidence", "accepted")
    result_id = OpaqueId.mint("result", "persisted")

    progress = controller.observe(
        "iteration-0",
        TaskIterationObservation(
            action=TaskIterationAction.CONTINUE,
            accepted_evidence_ids=(evidence_id,),
        ),
        is_root=False,
    )
    final = controller.observe(
        "iteration-1",
        TaskIterationObservation(
            action=TaskIterationAction.FINAL,
            result_artifact_id=result_id,
        ),
        is_root=False,
    )

    assert progress.stop is False
    assert progress.progress_value == 1
    assert final.phase is ChildEpisodePhase.SUCCEEDED
    assert final.accepted_result_id == result_id


def test_terminal_result_adapter_and_stagnation_are_host_decisions():
    terminal = TaskEpisodeController(
        _spec(TERMINAL_RESULT_PROGRESS_ADAPTER)
    )
    result_id = OpaqueId.mint("result", "terminal")
    final = terminal.observe(
        "iteration-0",
        TaskIterationObservation(
            action=TaskIterationAction.FINAL,
            result_artifact_id=result_id,
        ),
        is_root=False,
    )
    assert final.phase is ChildEpisodePhase.SUCCEEDED
    assert final.progress_value == 1

    stagnant = TaskEpisodeController(
        _spec(DURABLE_EVIDENCE_PROGRESS_ADAPTER, stagnation=2)
    )
    stagnant.observe(
        "iteration-0",
        TaskIterationObservation(action=TaskIterationAction.CONTINUE),
        is_root=False,
    )
    stopped = stagnant.observe(
        "iteration-1",
        TaskIterationObservation(action=TaskIterationAction.CONTINUE),
        is_root=False,
    )
    assert stopped.phase is ChildEpisodePhase.STOPPED
    assert stopped.stop_reason.value == "no_progress"


def test_task_episode_rejects_an_opaque_whole_turn_transport():
    with pytest.raises(ValueError, match="iteration-transparent"):
        hermes_iteration_source(
            agent=SimpleNamespace(api_mode="codex_app_server"),
            prompt="execute",
            spec=_spec(TERMINAL_RESULT_PROGRESS_ADAPTER),
            episode_id=OpaqueId.mint("episode", "opaque-transport").value,
            result_sink=lambda **_kwargs: OpaqueId.mint("result", "unused"),
        )
