"""Missing Episode modules are transcribed by the Builder's emitter, not a coding loop (#80).

Three Code Implementer turns over Argo spent 5.8–7.8M input tokens each without
writing a file; the Designer had assigned "a direct, mechanical transcription of
the admitted node plan", which EpisodeModuleEmitter performs in one call.
"""

from __future__ import annotations

import json
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

    # The repository conftest puts a HERMES_HOME under tmp_path; use a workspace of our own.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = TranscribedTurnSession(workspace=workspace, produce=fail)
    turn = session.run_turn("work")
    assert turn.error and "emission rejected" in turn.error
    assert not any(workspace.iterdir())
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
    assert sources.sources == {"built_episode_probe.py": "# built_episode_probe\n"} and sources.rejections == ()
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


# --- A validation rejection is feedback, not a failed model call -------------
# 2026-10-09: a 598 s Qwen3.8-27B emission rejected as goal_view_mutable became
# "implementer coding call failed; its owning Run must stop."


def _rejection(code="goal_view_mutable", source="def scope_goal_state(goal):\n    return {}\n"):
    from episode_builder.emitter import EpisodeEmissionError

    exc = EpisodeEmissionError(code=code, field_path="module_source.scope_goal_state",
                               detail="scope_goal_state must use the supplied goal when scoping the view",
                               episode_local_id="probe")
    exc.rejected_source = source
    return exc


def _emit(monkeypatch, emitter):
    import episode_builder.planner as planner

    monkeypatch.setattr(planner, "inherited_refinement_requests", lambda request, store: ())
    monkeypatch.setattr(planner, "approved_refinement_evidence_for_episode", lambda request, local_id, *, inherited: {})
    node = SimpleNamespace(local_id="probe", module_name="built_episode_probe")
    plan = SimpleNamespace(nodes=(node,), all_edges=())
    episodes = (SimpleNamespace(local_id="probe", contract="contract", episode_reference=None),)
    request = SimpleNamespace(frozen_workflow=SimpleNamespace(workflow=SimpleNamespace(episodes=episodes)))
    projection = SimpleNamespace(plan=plan, baseline=SimpleNamespace(build_request=request), modules=())

    async def transport(request):
        raise AssertionError("not called")

    return run_coroutine_privately(lambda: emit_modules(
        projection=projection, targets=(TranscriptionTarget("probe", "built_episode_probe.py"),),
        store=object(), transport=transport, emitter=emitter, resolver=object(),
    ))


class _ScriptedEmitter:
    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []

    async def emit(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return SimpleNamespace(module_source=outcome)


def test_a_rejection_gets_one_repair_attempt_with_the_rejection(monkeypatch) -> None:
    emitter = _ScriptedEmitter(_rejection(), "FIXED = 1\n")
    result = _emit(monkeypatch, emitter)
    assert result.sources == {"built_episode_probe.py": "FIXED = 1\n"} and result.rejections == ()
    first, second = emitter.calls
    assert "repair_feedback" not in first  # the ordinary Builder prompt is unchanged
    assert second["repair_feedback"]["code"] == "goal_view_mutable"
    assert second["repair_feedback"]["rejected_module_source"].startswith("def scope_goal_state")


def test_a_repeated_rejection_writes_the_rejected_source_for_admission(monkeypatch) -> None:
    emitter = _ScriptedEmitter(_rejection(), _rejection(source="SECOND = 2\n"))
    result = _emit(monkeypatch, emitter)
    assert result.sources == {"built_episode_probe.py": "SECOND = 2\n"}
    (rejection,) = result.rejections
    assert (rejection["code"], rejection["attempts"], rejection["source_written"]) == ("goal_view_mutable", 2, True)


def test_a_rejection_without_source_writes_nothing_but_is_not_fatal(monkeypatch) -> None:
    emitter = _ScriptedEmitter(_rejection("module_emission_failed", None), _rejection("module_emission_failed", None))
    result = _emit(monkeypatch, emitter)
    assert result.sources == {} and result.rejections[0]["source_written"] is False


def test_model_call_failures_still_stop_the_turn(monkeypatch) -> None:
    from llm_call_library.transport import ModelCallFailed

    emitter = _ScriptedEmitter(ModelCallFailed("provider down", {}))
    with pytest.raises(ModelCallFailed):
        _emit(monkeypatch, emitter)
    assert len(emitter.calls) == 1


def test_turn_with_a_rejection_succeeds_and_reports_it(tmp_path) -> None:
    rejection = {"local_id": "probe", "path": "built_episode_probe.py", "attempts": 2, "source_written": True,
                 "code": "goal_view_mutable", "field_path": "module_source.scope_goal_state", "detail": "use the goal"}
    produced = transcription.EmittedSources({"built_episode_probe.py": "SECOND = 2\n"}, (rejection,))
    session = TranscribedTurnSession(workspace=tmp_path, produce=lambda: produced)
    turn = session.run_turn("work")
    assert turn.error is None and "goal_view_mutable" in turn.final_text
    assert turn.native_result["rejections"][0]["code"] == "goal_view_mutable"
    assert (tmp_path / "built_episode_probe.py").read_text(encoding="utf-8") == "SECOND = 2\n"
    session.close()


def test_emitter_attaches_rejected_source_and_sends_repair_feedback(monkeypatch) -> None:
    import episode_builder.emitter as emitter_module

    prompts = []

    async def fake_completion(request):
        prompts.append(json.loads(request.prompt))
        return SimpleNamespace(succeeded=True, value=("RAW = 1\n", {"n": "x"}), failure=None)

    def reject(source, **kwargs):
        raise _rejection(source=None)

    monkeypatch.setattr(emitter_module, "structured_json_completion", fake_completion)
    monkeypatch.setattr(emitter_module, "complete_module_source", reject)
    monkeypatch.setattr(emitter_module, "observe_model_call", lambda *a, **k: None)
    monkeypatch.setattr(emitter_module, "materializer_function_catalog", lambda: [])
    monkeypatch.setattr(emitter_module.EpisodeModuleEmitter, "_validate_inputs", lambda self, *a: None)
    record = SimpleNamespace(as_record=lambda: {})
    plan = SimpleNamespace(as_record=lambda: {}, selected_function_bindings=(), parent_local_id=None, local_id="probe")
    emitter = emitter_module.EpisodeModuleEmitter.__new__(emitter_module.EpisodeModuleEmitter)
    from llm_call_library import CallOptions
    emitter.call_options = CallOptions(model_type="refinement")

    def emit(**extra):
        return run_coroutine_privately(lambda: emitter.emit(
            contract=record, plan=plan, direct_children={}, direct_edges=(), reference_context=None,
            target_module_name="built_episode_probe", **extra,
        ))

    with pytest.raises(emitter_module.EpisodeEmissionError) as caught:
        emit()
    assert caught.value.rejected_source == "RAW = 1\n"
    assert "rejected_previous_emission" not in prompts[0]
    with pytest.raises(emitter_module.EpisodeEmissionError):
        emit(repair_feedback={"code": "goal_view_mutable"})
    assert prompts[1]["rejected_previous_emission"] == {"code": "goal_view_mutable"}
