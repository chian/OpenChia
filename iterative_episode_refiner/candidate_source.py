"""Project candidate bytes through the Builder's existing source boundary.

Raw input remains campaign evidence. Only the host's deterministic declaration
attachment changes those bytes before admission. A rejected source never needs
to masquerade as a completed module or a fabricated model response.
"""

import asyncio
from dataclasses import dataclass, replace

from agent.duet_contracts import content_id

from episode_builder._contract_base import (
    BuildAttempt,
    BuildDeficit,
    EmittedEpisodeModule,
)
from episode_builder._contract_chain import WorkflowMaterializationPlan
from episode_builder.declaration import build_module_declaration
from episode_builder.emitter import (
    EpisodeEmissionError,
    _attach_host_declaration,
    complete_module_source,
)
from episode_builder.inspection import MaterializationInspectionInput
from episode_builder.service import _materializer_identity

from .materialization_edits import candidate_plan, source_paths
from .instrument_builds import SourceScope, source_scope


@dataclass(frozen=True)
class CandidateSources:
    baseline: MaterializationInspectionInput
    plan: WorkflowMaterializationPlan
    modules: tuple[EmittedEpisodeModule, ...]
    deficits: tuple[BuildDeficit, ...]
    raw_sources: dict[str, str]
    scope: SourceScope

    @property
    def completed_files(self):
        return {
            module.module_name.replace(".", "/") + ".py": module.source_hash.value
            for module in self.modules
        }


def source_kind(handoff, local_id):
    original = handoff["candidate"]["sources_by_episode"].get(local_id)
    return "candidate_raw_source" if original is None else original["kind"]


def project_candidate_sources(evidence, contract, candidate, binding=None):
    """Re-derive runnable bytes from durable candidate input, without writes."""
    scope = source_scope(evidence, contract, candidate, binding)
    inputs = scope.baseline
    if scope.fixed:
        return CandidateSources(
            inputs, inputs.plan, inputs.emitted_modules, (), {}, scope
        )
    plan = candidate_plan(
        evidence, contract, candidate, inputs, instrument=scope.instrument
    )
    handoff = scope.handoff
    paths = source_paths(inputs.build_request.frozen_workflow.workflow, plan)
    designs = {
        node.local_id: node.contract
        for node in inputs.build_request.frozen_workflow.workflow.episodes
    }
    modules, deficits, raw_sources = [], [], {}
    original_nodes = {node.local_id: node for node in inputs.plan.nodes}
    for node in plan.nodes:
        path = scope.paths[paths[node.local_id]]
        if path not in candidate.body["files"]:
            continue
        source_bytes = evidence.builds.read_blob(candidate.body["files"][path])
        edges = tuple(
            edge for edge in plan.all_edges if edge.parent_local_id == node.local_id
        )
        kind = source_kind(handoff, node.local_id)
        try:
            source = source_bytes.decode("utf-8")
            if not source.strip() or "\x00" in source:
                raise ValueError("source must be nonempty UTF-8 text without NUL bytes")
            declaration_changed = False
            if kind == "emitted_module":
                original = original_nodes[node.local_id]
                original_edges = tuple(
                    edge
                    for edge in inputs.plan.all_edges
                    if edge.parent_local_id == node.local_id
                )
                suffix = _attach_host_declaration(
                    "",
                    build_module_declaration(
                        designs[node.local_id], original, original_edges
                    ),
                )
                if not source.endswith(suffix):
                    raise EpisodeEmissionError(
                        code="host_declaration_changed",
                        field_path="module_source",
                        detail="the completed candidate must preserve its exact host-owned declaration",
                        episode_local_id=node.local_id,
                    )
                declaration_changed = suffix != _attach_host_declaration(
                    "", build_module_declaration(designs[node.local_id], node, edges)
                )
                source = source[: -len(suffix)]
            elif kind not in {"raw_model_source", "candidate_raw_source"}:
                raise ValueError("unknown source kind in materialization handoff")
            # This is candidate-derived input, not a claim that a model emitted
            # these bytes. The immutable candidate retains its full provenance.
            raw_sources[node.local_id] = source
            module = complete_module_source(
                source,
                contract=designs[node.local_id],
                plan=node,
                direct_edges=edges,
                forbidden_module_names=tuple(
                    other.module_name
                    for other in plan.nodes
                    if other.local_id != node.local_id
                ),
                derivation_notes={"refinement_candidate": candidate.artifact_id.value},
            )
            if (
                kind == "emitted_module"
                and not declaration_changed
                and module.source_hash.value != candidate.body["files"][path]
            ):
                raise EpisodeEmissionError(
                    code="host_declaration_changed",
                    field_path="module_source",
                    detail="completed source must retain the exact host declaration boundary",
                    episode_local_id=node.local_id,
                )
            modules.append(module)
        except EpisodeEmissionError as exc:
            deficits.append(exc.as_deficit())
        except ValueError as exc:
            deficits.append(
                BuildDeficit(
                    code="candidate_source_invalid",
                    field_path="module_source",
                    detail=str(exc).replace("\x00", " ")[:2048],
                    episode_local_id=node.local_id,
                )
            )
    return CandidateSources(
        inputs, plan, tuple(modules), tuple(deficits), raw_sources, scope
    )


def _inputs(store, contract, candidate, builder, binding=None):
    projection = project_candidate_sources(store.evidence, contract, candidate, binding)
    inputs = projection.baseline
    baseline_files = {
        module.module_name.replace(".", "/") + ".py": module.source_hash.value
        for module in inputs.emitted_modules
    }
    if (
        not projection.deficits
        and projection.plan == inputs.plan
        and projection.completed_files == baseline_files
        and inputs.receipt.materialized
    ):
        return inputs.receipt
    materializer = _materializer_identity(builder.planner.call_options, builder.emitter.call_options)
    request = replace(inputs.build_request, request_nonce=content_id("candidate_admission", {
        "campaign_ref": contract.ref.as_record(), "candidate_ref": candidate.ref.as_record(),
        "binding": binding, "materializer": materializer.as_record(),
    }).value)
    attempt = BuildAttempt(
        build_request_id=request.build_request_id,
        materializer=materializer,
        nonce=content_id("source_admission", {"request": request.build_request_id.value}).value,
    )
    plan = replace(
        projection.plan,
        build_request_id=request.build_request_id,
        build_attempt_id=attempt.build_attempt_id,
    )
    return request, attempt, plan, projection


def admit_candidate(store, contract, candidate, builder, binding=None):
    if builder.store is not store.evidence.builds:
        raise ValueError(
            "candidate admission must use the campaign's existing BuildStore"
        )
    prepared = _inputs(store, contract, candidate, builder, binding)
    if not isinstance(prepared, tuple):
        return prepared
    request, attempt, plan, projection = prepared
    receipts = builder.store.receipts_for_build_request(request.build_request_id)
    if receipts:
        if len(receipts) != 1 or receipts[0].build_attempt_id != attempt.build_attempt_id:
            raise ValueError("candidate source admission has conflicting receipts")
        return receipts[0]
    # Called on the host transaction thread, never the executor event loop.
    # Builder writes are content-addressed and independently retry-safe.
    return asyncio.run(builder.admit_sources(
        build_request=request,
        build_attempt=attempt,
        plan=plan,
        emitted_modules=projection.modules,
        source_deficits=projection.deficits,
    ))


def materialization_results(evidence, contract, candidate, receipt):
    """Use the Builder's recorded checks plus exact candidate-derived raw source.

    Repaired source has campaign provenance, not an emission call. Supplying it
    to the same source-shape function fills that explicit prerequisite without
    forging a model response or treating static checks as runtime observations.
    """
    from agent.episode_contracts import Sha256Digest
    from function_library.materialization_checks import (
        NODE_PLAN_CONSISTENCY,
        SOURCE_SHAPE,
    )
    from .plan_repair import resolve_plan_reference

    projection = project_candidate_sources(evidence, contract, candidate)
    handoff = evidence.materialization_handoff(receipt, contract.body["duet_id"])
    baseline = evidence.materialization_handoff(
        projection.baseline.receipt, contract.body["duet_id"]
    )
    if (
        handoff["requirements"] != baseline["requirements"]
        or handoff["checks"] != baseline["checks"]
    ):
        raise ValueError(
            "static requirements or check definitions drifted during refinement"
        )
    checks = {check["check_id"]: check for check in handoff["checks"]}
    targets = {
        episode["stable_target"] + "/parts/" + part: episode["local_id"]
        for episode in handoff["materialized_specification"]["episodes"]
        for part in ("emitted_module", "node_plan")
    }
    nodes = {node.local_id: node for node in projection.plan.nodes}
    designs = {
        design.local_id: design
        for design in projection.baseline.build_request.frozen_workflow.workflow.episodes
    }
    outcomes = {}
    for observed in handoff["observations"]:
        check = checks[observed["check_id"]]
        outcome = {**observed, "candidate_ref": candidate.ref.as_record()}
        if check["definition_id"] == NODE_PLAN_CONSISTENCY.definition_id:
            local_id = targets[check["target"]]
            node = nodes.get(local_id)
            if node is not None and node.reference_episode_id is not None:
                try:
                    context = resolve_plan_reference(designs[local_id], node)
                except (TypeError, ValueError) as exc:
                    outcome = {
                        **outcome,
                        "status": "blocked",
                        "reason": f"Pinned reference is unavailable: {exc}",
                    }
                else:
                    outcome = {
                        **outcome,
                        **NODE_PLAN_CONSISTENCY.load()(
                            projection.baseline.build_request,
                            projection.plan,
                            local_id,
                            reference_context=context,
                        ),
                        "reference_evidence_hash": node.reference_evidence_hash.value,
                        "source_origin": "candidate_plan_projection",
                    }
        if check["definition_id"] == SOURCE_SHAPE.definition_id:
            local_id = targets[check["target"]]
            raw = projection.raw_sources.get(local_id)
            if raw is not None:
                node = nodes[local_id]
                outcome = {
                    **outcome,
                    **SOURCE_SHAPE.load()(
                        raw,
                        local_id=local_id,
                        target_module_name=node.module_name,
                        forbidden_module_names=tuple(
                            other.module_name
                            for other in nodes.values()
                            if other.local_id != local_id
                        ),
                        is_root=node.parent_local_id is None,
                    ),
                    "source_hash": Sha256Digest.of_bytes(raw.encode("utf-8")).value,
                    "source_origin": "candidate_projection",
                }
                outcome.pop("reason", None)
        outcomes[check["check_id"]] = {"check": check, "observation": outcome}
    return outcomes
