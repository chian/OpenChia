"""Missing Episode modules are transcribed by the Builder's emitter, not a coding loop (#80).

Three Code Implementer turns over Argo spent 5.8–7.8M input tokens each without
writing a file; the Designer had assigned "a direct, mechanical transcription of
the admitted node plan", which EpisodeModuleEmitter performs in one call.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import iterative_episode_refiner.transcription as transcription
from iterative_episode_refiner.transcription import (
    TranscribedTurnSession, TranscriptionTarget, emit_modules, run_coroutine_privately,
    transcription_targets,
)

PATHS = {"probe": "built_episode_probe.py", "child": "built_episode_child.py"}


def test_targets_are_missing_assigned_episode_modules(tmp_path) -> None:
    assert transcription_targets(["built_episode_probe.py"], PATHS, tmp_path) == (
        TranscriptionTarget("probe", "built_episode_probe.py"),
    )


def test_existing_source_or_non_module_paths_go_to_the_coding_agent(tmp_path) -> None:
    (tmp_path / "built_episode_probe.py").write_text("X = 1\n", encoding="utf-8")
    assert transcription_targets(["built_episode_probe.py"], PATHS, tmp_path) == ()  # repair
    assert transcription_targets(["built_episode_child.py", ".openchia-environment.json"], PATHS, tmp_path) == ()
    assert transcription_targets([], PATHS, tmp_path) == ()


def test_disable_switch(monkeypatch) -> None:
    monkeypatch.setenv("OPENCHIA_REFINER_TRANSCRIPTION", "0")
    assert not transcription.transcription_enabled()
    monkeypatch.setenv("OPENCHIA_REFINER_TRANSCRIPTION", "1")
    assert transcription.transcription_enabled()


def test_turn_writes_emitted_sources_and_reports_them(tmp_path) -> None:
    session = TranscribedTurnSession(workspace=tmp_path, produce=lambda: {"pkg/built_episode_probe.py": "SOURCE = 1\n"})
    session.ensure_started()
    turn = session.run_turn("work")
    assert turn.error is None and turn.native_result["finish"] == "transcribed"
    assert (tmp_path / "pkg/built_episode_probe.py").read_text(encoding="utf-8-sig") == "SOURCE = 1\n"
    session.close()


def test_sentinel_identity_is_live_until_close(tmp_path) -> None:
    import os
    from openchia_cli.active_sessions import _pid_liveness

    session = TranscribedTurnSession(workspace=tmp_path, produce=dict)
    identity = session.process_identity()
    assert identity["pid"] != os.getpid() and _pid_liveness(identity["pid"], identity["process_start_time"]) is True
    session.close()
    assert _pid_liveness(identity["pid"], identity["process_start_time"]) is False


def test_emitter_failure_is_a_turn_error_and_writes_nothing(tmp_path) -> None:
    def fail():
        raise RuntimeError("emission rejected")

    session = TranscribedTurnSession(workspace=tmp_path, produce=fail)
    turn = session.run_turn("work")
    assert turn.error and "emission rejected" in turn.error
    assert not any(tmp_path.iterdir())
    session.close()


def test_paths_outside_the_workspace_are_refused(tmp_path) -> None:
    session = TranscribedTurnSession(workspace=tmp_path / "ws", produce=lambda: {"../escape.py": "X"})
    (tmp_path / "ws").mkdir()
    turn = session.run_turn("work")
    assert turn.error and "outside the coding workspace" in turn.error
    assert not (tmp_path / "escape.py").exists()
    session.close()


def test_emit_modules_passes_the_builders_inputs(monkeypatch) -> None:
    import episode_builder.planner as planner

    monkeypatch.setattr(planner, "inherited_refinement_requests", lambda request, store: ("inherited",))
    monkeypatch.setattr(planner, "approved_refinement_evidence_for_episode",
                        lambda request, local_id, *, inherited: {"local_id": local_id, "inherited": inherited})
    node_probe = SimpleNamespace(local_id="probe", module_name="built_episode_probe")
    node_child = SimpleNamespace(local_id="child", module_name="built_episode_child")
    edge = SimpleNamespace(parent_local_id="probe", child_local_id="child", slot_name="slot")
    plan = SimpleNamespace(nodes=(node_probe, node_child), all_edges=(edge,))
    episodes = tuple(SimpleNamespace(local_id=x, contract=f"contract-{x}", episode_reference=None)
                     for x in ("probe", "child"))
    request = SimpleNamespace(frozen_workflow=SimpleNamespace(workflow=SimpleNamespace(episodes=episodes)))
    predecessor = SimpleNamespace(module_name="built_episode_probe", module_source="OLD")
    projection = SimpleNamespace(plan=plan, baseline=SimpleNamespace(build_request=request), modules=(predecessor,))
    calls = []

    class FakeEmitter:
        async def emit(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(module_source=f"# {kwargs['target_module_name']}\n")

    seen_transport = []

    async def transport(request):  # never called by the fake emitter
        seen_transport.append(request)

    sources = run_coroutine_privately(lambda: emit_modules(
        projection=projection, targets=(TranscriptionTarget("probe", "built_episode_probe.py"),),
        store=object(), transport=transport, emitter=FakeEmitter(), resolver=object(),
    ))
    assert sources == {"built_episode_probe.py": "# built_episode_probe\n"}
    (call,) = calls
    assert call["contract"] == "contract-probe" and call["plan"] is node_probe
    assert call["direct_children"] == {"slot": node_child} and call["direct_edges"] == (edge,)
    assert call["forbidden_module_names"] == ("built_episode_child",)
    assert call["predecessor_module"] is predecessor
    assert call["approved_refinement_evidence"] == {"local_id": "probe", "inherited": ("inherited",)}


def test_private_loop_propagates_errors() -> None:
    async def boom():
        raise ValueError("x")

    with pytest.raises(ValueError):
        run_coroutine_privately(boom)
