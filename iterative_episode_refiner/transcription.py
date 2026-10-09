"""Construct missing Episode modules with the Builder's emitter instead of a coding loop.

When the Code Implementer is assigned Episode module paths that do not exist yet,
the work is a transcription of the admitted node plan. ``EpisodeModuleEmitter``
does that with one structured model call per module, using the same module
contract, approved refinement directives and predecessor evidence as the
Builder. The written files then go through the ordinary capture, admission and
local measurement; repair of existing source still uses the coding agent.

Cost (#80): one emitter call is roughly 50–150k input tokens; an exploratory
chat-completions coding turn on Argo used 5.8–7.8M.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from agent.refinement_coding import CodingTurn

#: Set to ``0`` to disable emitter transcription and always use the coding agent.
TRANSCRIPTION_ENV = "OPENCHIA_REFINER_TRANSCRIPTION"


@dataclass(frozen=True)
class TranscriptionTarget:
    local_id: str
    path: str


def transcription_enabled() -> bool:
    return os.environ.get(TRANSCRIPTION_ENV, "1").strip() not in {"0", "false", "no", "off"}


def transcription_targets(writable_paths, paths_by_local_id: Mapping[str, str], workspace_root) -> tuple[TranscriptionTarget, ...]:
    """Assigned Episode module paths that are still missing from the workspace.

    Every writable path must be an Episode module of the plan and none may exist
    yet; otherwise the assignment is repair or mixed work for the coding agent.
    """
    writable = set(writable_paths)
    by_path = {path: local_id for local_id, path in paths_by_local_id.items()}
    if not writable or not writable.issubset(by_path):
        return ()
    root = Path(workspace_root)
    if any((root / path).exists() for path in writable):
        return ()
    return tuple(TranscriptionTarget(by_path[path], path) for path in sorted(writable))


async def emit_modules(*, projection, targets, store, transport, emitter=None, resolver=None):
    """Emit each target module from the admitted plan; return ``{path: source}``."""
    from episode_builder.emitter import EpisodeModuleEmitter
    from episode_builder.planner import (
        approved_refinement_evidence_for_episode,
        inherited_refinement_requests,
    )
    from episode_builder.reference import EpisodeReferenceResolver
    from llm_call_library import CallOptions
    from llm_call_library.transport import model_transport_scope

    plan = projection.plan
    build_request = projection.baseline.build_request
    frozen_by_id = {episode.local_id: episode for episode in build_request.frozen_workflow.workflow.episodes}
    node_by_id = {node.local_id: node for node in plan.nodes}
    children_by_parent: dict[str, dict] = {}
    edges_by_parent: dict[str, list] = {}
    for edge in plan.all_edges:
        children_by_parent.setdefault(edge.parent_local_id, {})[edge.slot_name] = node_by_id[edge.child_local_id]
        edges_by_parent.setdefault(edge.parent_local_id, []).append(edge)
    module_names = tuple(node.module_name for node in plan.nodes)
    predecessors = {module.module_name: module for module in projection.modules}
    emitter = emitter or EpisodeModuleEmitter(call_options=CallOptions(model_type="refinement"))
    resolver = resolver or EpisodeReferenceResolver()
    inherited = inherited_refinement_requests(build_request, store)
    sources: dict[str, str] = {}
    from agent.refiner_role_routes import role_scope

    # Emitter calls are attributed to the "emitter" role so they can use their own
    # model/reasoning (e.g. deep reasoning for one long call), see refiner_role_routes.
    with model_transport_scope(transport), role_scope("emitter"):
        for target in targets:
            node = node_by_id[target.local_id]
            frozen = frozen_by_id[target.local_id]
            reference = None if frozen.episode_reference is None else resolver.resolve(frozen.episode_reference)
            module = await emitter.emit(
                contract=frozen.contract,
                plan=node,
                direct_children=children_by_parent.get(node.local_id, {}),
                direct_edges=tuple(edges_by_parent.get(node.local_id, ())),
                reference_context=reference,
                target_module_name=node.module_name,
                forbidden_module_names=tuple(name for name in module_names if name != node.module_name),
                approved_refinement_evidence=approved_refinement_evidence_for_episode(
                    build_request, node.local_id, inherited=inherited,
                ),
                predecessor_module=predecessors.get(node.module_name),
            )
            sources[target.path] = module.module_source
    return sources


class TranscribedTurnSession:
    """A ``CodingSession`` whose single turn writes emitter output into the workspace.

    It satisfies the Implementer's coding-session protocol so capture, proposal
    admission and audit stay unchanged. A sentinel process carries the session's
    liveness for the refiner's resume check.
    """

    runtime_id = "episode_module_emitter"

    def __init__(self, *, workspace, produce):
        self._workspace = Path(workspace)
        self._produce = produce  # () -> {path: source}; runs the emitter on a private loop
        self._thread_id = uuid.uuid4().hex
        self._sentinel = None
        self._interrupted = threading.Event()

    def ensure_started(self) -> str:
        if self._sentinel is None:
            self._sentinel = subprocess.Popen(
                [sys.executable, "-I", "-S", "-c", "import sys; sys.stdin.read()"],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        return self._thread_id

    def process_identity(self) -> dict:
        from openchia_cli.active_sessions import _process_start_time

        self.ensure_started()
        started = _process_start_time(self._sentinel.pid)
        if started is None:
            raise RuntimeError("transcription session process identity is unavailable")
        return {"pid": self._sentinel.pid, "process_start_time": started}

    def request_interrupt(self) -> None:
        self._interrupted.set()

    def run_turn(self, prompt, *, turn_timeout=None) -> CodingTurn:
        turn_id = uuid.uuid4().hex
        if self._interrupted.is_set():
            return CodingTurn(thread_id=self._thread_id, turn_id=turn_id, interrupted=True)
        try:
            sources = self._produce()
        except Exception as exc:
            return CodingTurn(thread_id=self._thread_id, turn_id=turn_id,
                              error=f"Emitter transcription failed: {type(exc).__name__}: {exc}"[:2000])
        for path, source in sources.items():
            target = (self._workspace / path).resolve()
            if self._workspace.resolve() not in target.parents:
                return CodingTurn(thread_id=self._thread_id, turn_id=turn_id,
                                  error=f"Emitter target {path!r} is outside the coding workspace")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8")
        return CodingTurn(
            final_text=("Transcribed the admitted node plan with the Builder's module emitter: "
                        + ", ".join(sorted(sources)) + ". Ordinary admission and local measurement judge it."),
            thread_id=self._thread_id, turn_id=turn_id, tool_iterations=len(sources),
            native_result={"finish": "transcribed", "paths": sorted(sources)},
        )

    def close(self) -> None:
        sentinel, self._sentinel = self._sentinel, None
        if sentinel is not None:
            try:
                if sentinel.stdin is not None:
                    sentinel.stdin.close()
                sentinel.wait(timeout=5)
            except Exception:
                sentinel.kill()
                sentinel.wait(timeout=5)


def run_coroutine_privately(make_coroutine):
    """Run a coroutine to completion on a private event loop in a worker thread.

    ``run_turn`` is synchronous and called from the refiner's event loop thread,
    so the emitter (async) runs on its own loop rather than re-entering that one.
    """
    result: dict = {}

    def target():
        try:
            result["value"] = asyncio.run(make_coroutine())
        except BaseException as exc:  # surfaced to the caller
            result["error"] = exc

    worker = threading.Thread(target=target, name="openchia-transcription", daemon=True)
    worker.start()
    worker.join()
    if "error" in result:
        raise result["error"]
    return result["value"]


__all__ = [
    "TRANSCRIPTION_ENV", "TranscribedTurnSession", "TranscriptionTarget", "emit_modules",
    "run_coroutine_privately", "transcription_enabled", "transcription_targets",
]
