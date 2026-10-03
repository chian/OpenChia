"""Inert source materialization for one exact approved build request.

Every invocation creates a fresh content-addressed BuildAttempt.  The service
may ask models to plan and author source, but it never imports generated source
or launches an Episode runtime.
"""

from __future__ import annotations

import asyncio
import ast
from collections.abc import Callable, Mapping
from dataclasses import replace
from enum import Enum
from pathlib import Path
import secrets
from types import MappingProxyType
from typing import Protocol

from agent.episode_contracts import OpaqueId, Sha256Digest
from iterative_episode_refiner.contracts import RefinementChangeKind
from llm_call_library import CallOptions, ModelTier

from .admission import EpisodeBuildAdmission
from ._contract_base import (
    BuildAttempt,
    BuildDeficit,
    BuildReceipt,
    EmittedEpisodeModule,
    MaterializerIdentity,
)
from ._contract_chain import (
    ApprovedBuildRequest,
    BuildManifest,
    WorkflowMaterializationPlan,
)
from ._contract_plan import (
    EdgeMaterializationPlan,
    NodeMaterializationPlan,
)
from .emitter import EpisodeEmissionError, EpisodeModuleEmitter
from .evidence import BuildCallEvidenceRecorder
from .planner import (
    EpisodeMaterializationPlanner,
    approved_refinement_evidence_for_episode,
    materializer_function_catalog,
)
from .reference import EpisodeReferenceResolver
from .store import BuildStore


ProgressCallback = Callable[[Mapping[str, object]], None]


class CancellationSignal(Protocol):
    """The narrow cancellation surface accepted from the host."""

    def is_set(self) -> bool: ...


def _blocking_count(deficits: tuple[BuildDeficit, ...]) -> int:
    return sum(deficit.blocking for deficit in deficits)


def _failure_deficit(
    code: str,
    field_path: str,
    error: Exception,
    *,
    local_id: str | None = None,
) -> BuildDeficit:
    return BuildDeficit(
        code=code,
        field_path=field_path,
        detail=f"{type(error).__name__}: {error}"[:2048],
        episode_local_id=local_id,
    )


def _root_local_id(build_request: ApprovedBuildRequest) -> str:
    return next(
        episode.local_id
        for episode in build_request.frozen_workflow.workflow.episodes
        if episode.workflow_parent_local_id is None
    )


def _leaf_first_nodes(
    plan: WorkflowMaterializationPlan,
) -> tuple[NodeMaterializationPlan, ...]:
    by_id = {node.local_id: node for node in plan.nodes}

    def depth(node: NodeMaterializationPlan) -> int:
        value = 0
        parent = node.parent_local_id
        while parent is not None and parent in by_id:
            value += 1
            parent = by_id[parent].parent_local_id
        return value

    return tuple(sorted(plan.nodes, key=lambda node: (-depth(node), node.local_id)))


_SECRET_KEY_PARTS = (
    "api_key",
    "access_key",
    "auth_token",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "credential",
    "private_key",
    "cookie",
)


def _safe_route_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for raw_key in sorted(value, key=str):
            key = str(raw_key)
            lowered = key.lower().replace("-", "_")
            if any(part in lowered for part in _SECRET_KEY_PARTS):
                continue
            result[key] = _safe_route_value(value[raw_key])
        return result
    if isinstance(value, (tuple, list)):
        return [_safe_route_value(item) for item in value]
    return {
        "configured_type": f"{type(value).__module__}.{type(value).__qualname__}"
    }


def _model_config(options: CallOptions) -> Mapping[str, object]:
    auxiliary_task = (
        "episode_structured_json_fast"
        if options.tier is ModelTier.FAST
        else "episode_structured_json_reasoning"
    )
    return {
        "transport_boundary": "llm_call_library.call_model_transport",
        "auxiliary_task": auxiliary_task,
        "route_mode": (
            "explicit_launch" if options.launch_configuration_hash is not None
            else "host_default" if options.main_runtime is None else "main_runtime"
        ),
        "launch_configuration_hash": options.launch_configuration_hash,
        "tier": options.tier.value,
        "model_type": options.model_type,
        "temperature": options.temperature,
        "max_tokens": options.max_tokens,
        "timeout": options.timeout,
        "main_runtime": (
            None
            if options.main_runtime is None
            else _safe_route_value(options.main_runtime)
        ),
    }


def _materializer_identity(planning_options: CallOptions, emission_options: CallOptions) -> MaterializerIdentity:
    package = Path(__file__).resolve().parent
    sources = {
        f"episode_builder/{path.name}": Sha256Digest.of_bytes(path.read_bytes())
        for path in sorted(package.glob("*.py"), key=lambda item: item.name)
        if path.is_file()
    }
    return MaterializerIdentity(
        builder_source_hashes=sources,
        function_catalog=materializer_function_catalog(),
        planner_model_config={
            "planning": _model_config(planning_options),
            "emission": _model_config(emission_options),
        },
    )


def _incremental_predecessor_plan_id(
    request: ApprovedBuildRequest,
) -> OpaqueId | None:
    decision = request.refinement_decision
    if (
        decision is not None
        and decision.kind is RefinementChangeKind.IMPLEMENTATION_PRESERVING
        and request.predecessor_manifest is not None
    ):
        return request.predecessor_manifest.plan_id
    return None


def _pointer_token_value(value: str) -> str:
    return value.replace("~1", "/").replace("~0", "~")


def _top_level_symbol_inventory(
    source: str,
) -> tuple[dict[str, str], str]:
    tree = ast.parse(source, mode="exec")
    symbols: dict[str, str] = {}
    counts: dict[str, int] = {}
    residual: list[ast.stmt] = []
    for statement in tree.body:
        names: list[str] = []
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(statement.name)
        elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else (statement.target,)
            )
            names.extend(target.id for target in targets if isinstance(target, ast.Name))
        keys: list[str] = []
        for name in names:
            count = counts.get(name, 0) + 1
            counts[name] = count
            key = name if count == 1 else f"{name}#{count}"
            symbols[key] = ast.dump(statement, include_attributes=False)
            keys.append(key)
        if keys:
            residual.append(ast.Expr(value=ast.Constant(value=tuple(keys))))
        else:
            residual.append(statement)
    tree.body = residual
    return symbols, ast.dump(tree, include_attributes=False)


def _directive_source_scope_deficit(
    build_request: ApprovedBuildRequest,
    predecessor: EmittedEpisodeModule,
    successor: EmittedEpisodeModule,
) -> BuildDeficit | None:
    proposal = build_request.refinement_proposal
    if proposal is None:
        return None
    pointers = tuple(
        item.target.json_pointer
        for item in proposal.implementation_directives
        if item.target.episode_local_id in {None, successor.local_id}
    )
    if any(
        item.target.episode_local_id is None
        for item in proposal.implementation_directives
    ):
        return None
    episode_base = f"/episodes/{successor.local_id}"
    if any(
        pointer == episode_base
        or (
            pointer.startswith(episode_base + "/parts/")
            and "/source_symbols/" not in pointer
        )
        for pointer in pointers
    ):
        return None
    if any(
        pointer.endswith(
            (
                "/parts/emitted_module",
                "/parts/node_plan",
                "/parts/parent_owned_edges",
            )
        )
        for pointer in pointers
    ):
        return None
    prefix = f"/episodes/{successor.local_id}/source_symbols/"
    target_symbols = {
        _pointer_token_value(pointer.removeprefix(prefix))
        for pointer in pointers
        if pointer.startswith(prefix)
    }
    if not target_symbols:
        return BuildDeficit(
            code="directive_source_scope_missing",
            field_path="module_source",
            detail="directive does not authorize a source or plan part",
            episode_local_id=successor.local_id,
        )
    predecessor_symbols, predecessor_residual = _top_level_symbol_inventory(
        predecessor.module_source
    )
    successor_symbols, successor_residual = _top_level_symbol_inventory(
        successor.module_source
    )
    if not target_symbols.issubset(predecessor_symbols) or not target_symbols.issubset(
        successor_symbols
    ):
        return BuildDeficit(
            code="directive_source_target_missing",
            field_path="module_source",
            detail="approved source-symbol target is absent before or after refinement",
            episode_local_id=successor.local_id,
        )
    predecessor_untargeted = {
        name: value
        for name, value in predecessor_symbols.items()
        if name not in target_symbols
    }
    successor_untargeted = {
        name: value
        for name, value in successor_symbols.items()
        if name not in target_symbols
    }
    if (
        predecessor_residual != successor_residual
        or predecessor_untargeted != successor_untargeted
    ):
        return BuildDeficit(
            code="directive_source_scope_exceeded",
            field_path="module_source",
            detail="successor source changes content outside approved source symbols",
            episode_local_id=successor.local_id,
        )
    return None


class EpisodeBuilder:
    """Materialize and statically admit an approved request as inert source."""

    def __init__(
        self,
        *,
        store: BuildStore,
        planning_options: CallOptions,
        emission_options: CallOptions,
        reference_resolver: EpisodeReferenceResolver | None = None,
        planner: EpisodeMaterializationPlanner | None = None,
        emitter: EpisodeModuleEmitter | None = None,
        admission: EpisodeBuildAdmission | None = None,
        model_slot_catalog: Mapping[str, object] | None = None,
    ) -> None:
        if not isinstance(store, BuildStore):
            raise TypeError("EpisodeBuilder requires a BuildStore")
        if not isinstance(planning_options, CallOptions) or not isinstance(emission_options, CallOptions):
            raise TypeError("Builder requires explicit planning_options and emission_options")
        resolver = reference_resolver
        if resolver is None and planner is not None:
            resolver = planner.reference_resolver
        resolver = resolver or EpisodeReferenceResolver()
        if not isinstance(resolver, EpisodeReferenceResolver):
            raise TypeError("reference_resolver must be an EpisodeReferenceResolver")
        if planner is not None and not isinstance(
            planner,
            EpisodeMaterializationPlanner,
        ):
            raise TypeError("planner must be an EpisodeMaterializationPlanner")
        if emitter is not None and not isinstance(emitter, EpisodeModuleEmitter):
            raise TypeError("emitter must be an EpisodeModuleEmitter")
        if admission is not None and not isinstance(admission, EpisodeBuildAdmission):
            raise TypeError("admission must be an EpisodeBuildAdmission")
        if planner is not None and planner.call_options != planning_options:
            raise ValueError("injected planner uses different model routing")
        if emitter is not None and emitter.call_options != emission_options:
            raise ValueError("injected emitter uses different model routing")
        if planner is not None and planner.reference_resolver is not resolver:
            raise ValueError(
                "planner and EpisodeBuilder must share one reference resolver"
            )
        self.store = store
        self.reference_resolver = resolver
        self.planner = planner or EpisodeMaterializationPlanner(
            reference_resolver=resolver,
            call_options=planning_options,
            model_slot_catalog=model_slot_catalog,
        )
        self.emitter = emitter or EpisodeModuleEmitter(call_options=emission_options)
        self.admission = admission or EpisodeBuildAdmission()

    @staticmethod
    def _validate_boundary(
        build_request: ApprovedBuildRequest,
        progress_callback: ProgressCallback | None,
        cancel_event: CancellationSignal | None,
    ) -> None:
        if not isinstance(build_request, ApprovedBuildRequest):
            raise TypeError("build requires ApprovedBuildRequest")
        if progress_callback is not None and not callable(progress_callback):
            raise TypeError("progress_callback must be callable")
        if cancel_event is not None and not callable(
            getattr(cancel_event, "is_set", None)
        ):
            raise TypeError("cancel_event must provide is_set()")

    @staticmethod
    def _cancelled(cancel_event: CancellationSignal | None) -> bool:
        return cancel_event is not None and cancel_event.is_set()

    @staticmethod
    def _notify(
        progress_callback: ProgressCallback | None,
        *,
        stage: str,
        local_id: str | None,
        episodes_total: int,
        episodes_planned: int,
        episodes_emitted: int,
        blocking_deficits: int,
        build_attempt_id: OpaqueId,
    ) -> None:
        if progress_callback is None:
            return
        progress_callback(
            {
                "stage": stage,
                "local_id": local_id,
                "build_attempt_id": build_attempt_id.value,
                "counts": {
                    "episodes_total": episodes_total,
                    "episodes_planned": episodes_planned,
                    "episodes_emitted": episodes_emitted,
                    "blocking_deficits": blocking_deficits,
                },
            }
        )

    def _persist_receipt(
        self,
        *,
        build_request: ApprovedBuildRequest,
        build_attempt: BuildAttempt,
        plan: WorkflowMaterializationPlan,
        status: str,
        admission_report_id: OpaqueId | None,
        manifest_id: OpaqueId | None,
        emitted_modules: Mapping[str, EmittedEpisodeModule],
        deficits: tuple[BuildDeficit, ...],
        progress_callback: ProgressCallback | None,
        stage: str,
        episodes_total: int,
    ) -> BuildReceipt:
        receipt = BuildReceipt(
            build_request_id=build_request.build_request_id,
            build_attempt_id=build_attempt.build_attempt_id,
            plan_id=plan.plan_id,
            status=status,
            admission_report_id=admission_report_id,
            manifest_id=manifest_id,
            emitted_module_ids_by_local_id={
                local_id: module.emitted_module_id
                for local_id, module in emitted_modules.items()
            },
            deficits=deficits,
        )
        self.store.put_receipt(receipt)
        self.store.publish_materialization_handoff(receipt.receipt_id)
        self._notify(
            progress_callback,
            stage=stage,
            local_id=None,
            episodes_total=episodes_total,
            episodes_planned=len(plan.nodes),
            episodes_emitted=len(emitted_modules),
            blocking_deficits=_blocking_count(deficits),
            build_attempt_id=build_attempt.build_attempt_id,
        )
        return receipt

    @staticmethod
    def _terminal_plan(
        build_request: ApprovedBuildRequest,
        build_attempt: BuildAttempt,
        deficit: BuildDeficit,
    ) -> WorkflowMaterializationPlan:
        return WorkflowMaterializationPlan(
            build_request_id=build_request.build_request_id,
            build_attempt_id=build_attempt.build_attempt_id,
            workflow_hash=build_request.frozen_workflow.workflow_hash,
            root_local_id=_root_local_id(build_request),
            nodes=(),
            edges=(),
            predecessor_plan_id=_incremental_predecessor_plan_id(build_request),
            node_dispositions={},
            deficits=(deficit,),
        )

    @staticmethod
    def _cancellation_deficit() -> BuildDeficit:
        return BuildDeficit(
            code="build_cancelled",
            field_path="build",
            detail=(
                "The host cancellation signal ended materialization between "
                "Builder stages."
            ),
        )

    def _incremental_evidence(
        self,
        build_request: ApprovedBuildRequest,
    ) -> tuple[
        WorkflowMaterializationPlan | None,
        Mapping[str, EmittedEpisodeModule],
    ]:
        predecessor_plan_id = _incremental_predecessor_plan_id(build_request)
        if predecessor_plan_id is None:
            return None, {}
        receipt = build_request.predecessor_receipt
        manifest = build_request.predecessor_manifest
        if receipt is None or manifest is None:
            raise ValueError("incremental evidence is incomplete")
        stored_receipt = self.store.read_receipt(receipt.receipt_id)
        stored_manifest = self.store.read_manifest(manifest.manifest_id)
        if (
            stored_receipt.as_record() != receipt.as_record()
            or stored_manifest.as_record() != manifest.as_record()
            or stored_receipt.manifest_id != stored_manifest.manifest_id
        ):
            raise ValueError("incremental evidence differs from the approved request")
        predecessor_plan = self.store.read_plan(predecessor_plan_id)
        modules = {
            local_id: self.store.read_emitted_module(identifier)
            for local_id, identifier in stored_receipt.emitted_module_ids_by_local_id.items()
        }
        if (
            set(modules) != set(stored_manifest.module_hashes_by_local_id)
            or any(
                module.source_hash
                != stored_manifest.module_hashes_by_local_id[local_id]
                for local_id, module in modules.items()
            )
        ):
            raise ValueError("predecessor module records differ from the manifest")
        return predecessor_plan, MappingProxyType(dict(sorted(modules.items())))

    async def build(
        self,
        build_request: ApprovedBuildRequest,
        progress_callback: ProgressCallback | None = None,
        cancel_event: CancellationSignal | None = None,
    ) -> BuildReceipt:
        """Create one fresh attempt and persist its exact terminal evidence."""

        self._validate_boundary(build_request, progress_callback, cancel_event)
        total = len(build_request.frozen_workflow.workflow.episodes)
        self.store.put_build_request(build_request)
        build_attempt = BuildAttempt(
            build_request_id=build_request.build_request_id,
            materializer=_materializer_identity(self.planner.call_options, self.emitter.call_options),
            nonce=secrets.token_hex(32),
        )
        self.store.put_build_attempt(build_attempt)
        model_call_observer = BuildCallEvidenceRecorder(
            store=self.store, build_attempt=build_attempt,
        )
        self._notify(
            progress_callback,
            stage="attempt_persisted",
            local_id=None,
            episodes_total=total,
            episodes_planned=0,
            episodes_emitted=0,
            blocking_deficits=0,
            build_attempt_id=build_attempt.build_attempt_id,
        )
        if self._cancelled(cancel_event):
            plan = self._terminal_plan(
                build_request,
                build_attempt,
                self._cancellation_deficit(),
            )
            self.store.put_plan(plan)
            return self._persist_receipt(
                build_request=build_request,
                build_attempt=build_attempt,
                plan=plan,
                status="failed",
                admission_report_id=None,
                manifest_id=None,
                emitted_modules={},
                deficits=plan.deficits,
                progress_callback=progress_callback,
                stage="cancelled",
                episodes_total=total,
            )
        try:
            predecessor_plan, predecessor_modules = self._incremental_evidence(
                build_request
            )
            plan = await self.planner.plan(
                build_request,
                build_attempt,
                predecessor_plan=predecessor_plan,
                model_call_observer=model_call_observer,
            )
        except asyncio.CancelledError:
            plan = self._terminal_plan(
                build_request,
                build_attempt,
                self._cancellation_deficit(),
            )
            self.store.put_plan(plan)
            return self._persist_receipt(
                build_request=build_request,
                build_attempt=build_attempt,
                plan=plan,
                status="failed",
                admission_report_id=None,
                manifest_id=None,
                emitted_modules={},
                deficits=plan.deficits,
                progress_callback=progress_callback,
                stage="cancelled",
                episodes_total=total,
            )
        except Exception as exc:
            plan = self._terminal_plan(
                build_request,
                build_attempt,
                _failure_deficit(
                    "planning_internal_failure",
                    "build.planning",
                    exc,
                ),
            )
            self.store.put_plan(plan)
            return self._persist_receipt(
                build_request=build_request,
                build_attempt=build_attempt,
                plan=plan,
                status="failed",
                admission_report_id=None,
                manifest_id=None,
                emitted_modules={},
                deficits=plan.deficits,
                progress_callback=progress_callback,
                stage="failed",
                episodes_total=total,
            )
        if self._cancelled(cancel_event):
            plan = replace(plan, deficits=(*plan.deficits, self._cancellation_deficit()))
            self.store.put_plan(plan)
            return self._persist_receipt(
                build_request=build_request,
                build_attempt=build_attempt,
                plan=plan,
                status="failed",
                admission_report_id=None,
                manifest_id=None,
                emitted_modules={},
                deficits=plan.deficits,
                progress_callback=progress_callback,
                stage="cancelled",
                episodes_total=total,
            )
        self.store.put_plan(plan)
        self._notify(
            progress_callback,
            stage="planned",
            local_id=None,
            episodes_total=total,
            episodes_planned=len(plan.nodes),
            episodes_emitted=0,
            blocking_deficits=_blocking_count(plan.deficits),
            build_attempt_id=build_attempt.build_attempt_id,
        )
        frozen_by_id = {
            episode.local_id: episode
            for episode in build_request.frozen_workflow.workflow.episodes
        }
        node_by_id = {node.local_id: node for node in plan.nodes}
        children_by_parent: dict[str, dict[str, NodeMaterializationPlan]] = {}
        edges_by_parent: dict[str, list[EdgeMaterializationPlan]] = {}
        for edge in plan.edges:
            children_by_parent.setdefault(edge.parent_local_id, {})[
                edge.slot_name
            ] = node_by_id[edge.child_local_id]
            edges_by_parent.setdefault(edge.parent_local_id, []).append(edge)
        module_names = tuple(node.module_name for node in plan.nodes)
        emitted: dict[str, EmittedEpisodeModule] = {}
        emission_deficits: list[BuildDeficit] = []
        for node in _leaf_first_nodes(plan):
            if self._cancelled(cancel_event):
                deficits = (*plan.deficits, *emission_deficits, self._cancellation_deficit())
                return self._persist_receipt(
                    build_request=build_request,
                    build_attempt=build_attempt,
                    plan=plan,
                    status="failed",
                    admission_report_id=None,
                    manifest_id=None,
                    emitted_modules=emitted,
                    deficits=deficits,
                    progress_callback=progress_callback,
                    stage="cancelled",
                    episodes_total=total,
                )
            # A blocked sibling does not prevent materializing a valid node.
            # Complete direct interfaces and this node's own obligations are
            # prerequisites; source never runs at this boundary.
            local_blockers = [
                item for item in plan.deficits
                if item.blocking and item.episode_local_id in {None, node.local_id}
            ]
            expected_children = {
                episode.local_id for episode in frozen_by_id.values()
                if episode.workflow_parent_local_id == node.local_id
            }
            actual_children = {
                edge.child_local_id for edge in edges_by_parent.get(node.local_id, ())
            }
            disposition = plan.node_dispositions.get(node.local_id)
            skip_reasons = []
            if local_blockers:
                skip_reasons.append(
                    "blocking plan findings: "
                    + ", ".join(sorted({item.code for item in local_blockers}))
                )
            if expected_children != actual_children:
                skip_reasons.append(
                    f"missing child interfaces: {sorted(expected_children - actual_children)!r}; "
                    f"unexpected child interfaces: {sorted(actual_children - expected_children)!r}"
                )
            if disposition is None:
                skip_reasons.append("node disposition is absent from the materialization plan")
            if skip_reasons:
                emission_deficits.append(BuildDeficit(
                    code="node_emission_skipped",
                    field_path="build.emission",
                    detail="; ".join(skip_reasons),
                    episode_local_id=node.local_id,
                ))
                continue
            if disposition == "unchanged":
                module = predecessor_modules.get(node.local_id)
                if module is None or module.module_name != node.module_name:
                    deficit = BuildDeficit(
                        code="unchanged_module_unavailable",
                        field_path="predecessor_manifest",
                        detail="unchanged plan has no exact predecessor module",
                        episode_local_id=node.local_id,
                    )
                    emission_deficits.append(deficit)
                    continue
                emitted[node.local_id] = module
                stage = "module_reused"
            else:
                frozen = frozen_by_id[node.local_id]
                reference_context = None
                if frozen.episode_reference is not None:
                    try:
                        reference_context = self.reference_resolver.resolve(
                            frozen.episode_reference
                        )
                    except Exception as exc:
                        deficit = _failure_deficit(
                            "reference_unavailable",
                            "episode_reference",
                            exc,
                            local_id=node.local_id,
                        )
                        emission_deficits.append(deficit)
                        continue
                try:
                    module = await self.emitter.emit(
                        contract=frozen.contract,
                        plan=node,
                        direct_children=children_by_parent.get(node.local_id, {}),
                        direct_edges=tuple(edges_by_parent.get(node.local_id, ())),
                        reference_context=reference_context,
                        target_module_name=node.module_name,
                        forbidden_module_names=tuple(
                            name for name in module_names if name != node.module_name
                        ),
                        approved_refinement_evidence=(
                            approved_refinement_evidence_for_episode(
                                build_request,
                                node.local_id,
                            )
                        ),
                        predecessor_module=predecessor_modules.get(node.local_id),
                        model_call_observer=model_call_observer,
                    )
                    if (
                        disposition == "directive"
                        and node.local_id in predecessor_modules
                    ):
                        scope_deficit = _directive_source_scope_deficit(
                            build_request,
                            predecessor_modules[node.local_id],
                            module,
                        )
                        if scope_deficit is not None:
                            emission_deficits.append(scope_deficit)
                            continue
                    self.store.put_emitted_module(module)
                except asyncio.CancelledError:
                    return self._persist_receipt(
                        build_request=build_request,
                        build_attempt=build_attempt,
                        plan=plan,
                        status="failed",
                        admission_report_id=None,
                        manifest_id=None,
                        emitted_modules=emitted,
                        deficits=(
                            *plan.deficits,
                            *emission_deficits,
                            self._cancellation_deficit(),
                        ),
                        progress_callback=progress_callback,
                        stage="cancelled",
                        episodes_total=total,
                    )
                except EpisodeEmissionError as exc:
                    deficit = exc.as_deficit()
                    emission_deficits.append(deficit)
                    continue
                except Exception as exc:
                    deficit = _failure_deficit(
                        "module_emission_internal_failure",
                        "module_source",
                        exc,
                        local_id=node.local_id,
                    )
                    emission_deficits.append(deficit)
                    continue
                emitted[node.local_id] = module
                stage = "module_emitted"
            if self._cancelled(cancel_event):
                return self._persist_receipt(
                    build_request=build_request,
                    build_attempt=build_attempt,
                    plan=plan,
                    status="failed",
                    admission_report_id=None,
                    manifest_id=None,
                    emitted_modules=emitted,
                    deficits=(*plan.deficits, *emission_deficits, self._cancellation_deficit()),
                    progress_callback=progress_callback,
                    stage="cancelled",
                    episodes_total=total,
                )
            self._notify(
                progress_callback,
                stage=stage,
                local_id=node.local_id,
                episodes_total=total,
                episodes_planned=len(plan.nodes),
                episodes_emitted=len(emitted),
                blocking_deficits=_blocking_count((*plan.deficits, *emission_deficits)),
                build_attempt_id=build_attempt.build_attempt_id,
            )
        try:
            outcome = await asyncio.to_thread(
                self.admission.admit_outcome,
                build_request,
                build_attempt,
                plan,
                tuple(emitted[key] for key in sorted(emitted)),
            )
            report = replace(
                outcome.report,
                deficits=(*outcome.report.deficits, *emission_deficits),
            )
            self.store.put_admission_report(report)
        except asyncio.CancelledError:
            return self._persist_receipt(
                build_request=build_request,
                build_attempt=build_attempt,
                plan=plan,
                status="failed",
                admission_report_id=None,
                manifest_id=None,
                emitted_modules=emitted,
                deficits=(*plan.deficits, *emission_deficits, self._cancellation_deficit()),
                progress_callback=progress_callback,
                stage="cancelled",
                episodes_total=total,
            )
        except Exception as exc:
            deficit = _failure_deficit(
                "source_inspection_failure",
                "build.admission",
                exc,
            )
            return self._persist_receipt(
                build_request=build_request,
                build_attempt=build_attempt,
                plan=plan,
                status="failed",
                admission_report_id=None,
                manifest_id=None,
                emitted_modules=emitted,
                deficits=(*plan.deficits, *emission_deficits, deficit),
                progress_callback=progress_callback,
                stage="failed",
                episodes_total=total,
            )
        if not report.admitted:
            return self._persist_receipt(
                build_request=build_request,
                build_attempt=build_attempt,
                plan=plan,
                status="blocked",
                admission_report_id=report.report_id,
                manifest_id=None,
                emitted_modules=emitted,
                deficits=report.deficits,
                progress_callback=progress_callback,
                stage="blocked",
                episodes_total=total,
            )
        if self._cancelled(cancel_event):
            deficits = (*report.deficits, self._cancellation_deficit())
            return self._persist_receipt(
                build_request=build_request,
                build_attempt=build_attempt,
                plan=plan,
                status="failed",
                admission_report_id=report.report_id,
                manifest_id=None,
                emitted_modules=emitted,
                deficits=deficits,
                progress_callback=progress_callback,
                stage="cancelled",
                episodes_total=total,
            )
        try:
            manifest = BuildManifest(
                build_request_id=build_request.build_request_id,
                build_attempt_id=build_attempt.build_attempt_id,
                plan_id=plan.plan_id,
                admission_report_id=report.report_id,
                predecessor_manifest_id=(
                    None
                    if build_request.predecessor_manifest is None
                    else build_request.predecessor_manifest.manifest_id
                ),
                workflow_hash=plan.workflow_hash,
                root_local_id=plan.root_local_id,
                root_module=node_by_id[plan.root_local_id].module_name,
                episode_ids_by_local_id=outcome.episode_ids_by_local_id,
                module_hashes_by_local_id=report.module_source_hashes,
                module_dispositions_by_local_id=plan.node_dispositions,
                function_definition_ids=outcome.function_definition_ids,
            )
            self.store.put_manifest(manifest)
            self.store.publish_source_package(manifest)
        except Exception as exc:
            deficit = _failure_deficit(
                "source_package_failure",
                "build.persistence",
                exc,
            )
            return self._persist_receipt(
                build_request=build_request,
                build_attempt=build_attempt,
                plan=plan,
                status="failed",
                admission_report_id=report.report_id,
                manifest_id=None,
                emitted_modules=emitted,
                deficits=(*report.deficits, deficit),
                progress_callback=progress_callback,
                stage="failed",
                episodes_total=total,
            )
        return self._persist_receipt(
            build_request=build_request,
            build_attempt=build_attempt,
            plan=plan,
            status="materialized",
            admission_report_id=report.report_id,
            manifest_id=manifest.manifest_id,
            emitted_modules=emitted,
            deficits=report.deficits,
            progress_callback=progress_callback,
            stage="materialized",
            episodes_total=total,
        )


__all__ = ["CancellationSignal", "EpisodeBuilder", "ProgressCallback"]
