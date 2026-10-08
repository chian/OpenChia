"""Persist the initial materialization evidence consumed by a Refiner.

The approved architecture fixes the requirements. Candidate bytes and check
observations are separate: a diagnostic is evidence about a requirement, not
an extra unit of progress. Generated source is always inspected as inert data.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import cache
from importlib.util import find_spec
from pathlib import Path
import sys

from agent.duet_contracts import content_id
from agent.episode_contracts import OpaqueId, Sha256Digest
from function_library.materialization_checks import (
    MODULE_ADMISSION,
    NODE_PLAN_CONSISTENCY,
    PLAN_CONSISTENCY,
    RECEIPT_MATERIALIZED,
    SOURCE_SHAPE,
    materialization_check_library,
)
from function_library.materialization_progress import (
    REQUIREMENT_SATISFACTION,
    requirement_satisfaction,
)

from .evidence import model_call_evidence_for_attempt
from .inspection import project_materialized_specification
from .store import BuildStore


def _identified(prefix: str, record: dict) -> dict:
    return {
        "artifact_id": content_id(prefix, record).value,
        "content_hash": Sha256Digest.of_record(record).value,
        **record,
    }


def _ref(record: Mapping) -> dict:
    return {key: record[key] for key in ("artifact_id", "content_hash")}


def _blocked(reason: str) -> dict:
    return {"status": "blocked", "diagnostics": [], "reason": reason}


def _source_candidates(store, inputs, calls):
    """Select emitted bytes, or the sole captured raw source when emission failed."""
    from .planner import _module_name
    from .source_inputs import read_source_inputs

    submitted = read_source_inputs(store, inputs)
    modules = {module.local_id: module for module in inputs.emitted_modules}
    nodes = {node.local_id: node for node in inputs.plan.nodes}
    files, sources = {}, {}
    for design in inputs.build_request.frozen_workflow.workflow.episodes:
        local_id = design.local_id
        node = nodes.get(local_id)
        raw_sources = sorted({
            call["module_source_hash"] for call in calls
            if call["stage"] == "emission" and call["local_id"] == local_id
            and call["module_source_hash"] is not None
        })
        if submitted is not None and local_id in submitted["sources"]:
            raw_sources = [submitted["sources"][local_id]]
        module = modules.get(local_id)
        digest = module.source_hash.value if module else (
            raw_sources[0] if len(raw_sources) == 1 else None
        )
        sources[local_id] = {
            "source_hash": digest,
            "kind": "emitted_module" if module else (
                "submitted_source" if submitted is not None and local_id in submitted["sources"]
                else "raw_model_source"
            ),
            "raw_source_hashes": raw_sources,
            "emitted_module_id": None if module is None else module.emitted_module_id.value,
            **({"submitted_source_ref": _ref(submitted)} if submitted is not None else {}),
        }
        if digest is not None:
            store.read_blob(digest)
            name = node.module_name if node is not None else _module_name(local_id, design.contract.spec_hash.value)
            files[BuildStore._package_module_path(name).as_posix()] = digest
    if inputs.manifest is not None and inputs.manifest.environment_recipe is not None:
        from agent.duet_contracts import canonical_json
        from episode_runtime.target_environment import ENVIRONMENT_RECIPE_PATH

        recipe = inputs.manifest.as_record()["environment_recipe"]
        files[ENVIRONMENT_RECIPE_PATH] = store.put_blob(canonical_json(recipe).encode("utf-8")).value
    elif submitted is not None and submitted["environment_source"] is not None:
        from episode_runtime.target_environment import ENVIRONMENT_RECIPE_PATH

        files[ENVIRONMENT_RECIPE_PATH] = submitted["environment_source"]
    return dict(sorted(files.items())), sources


def _diagnostic_index(specification):
    indexed = {}
    for projected in specification.deficits:
        record = projected.deficit.as_record()
        identifier = content_id("materialization_diagnostic", record).value
        item = indexed.setdefault(identifier, {
            "diagnostic_id": identifier, **record, "origins": [],
        })
        if projected.origin not in item["origins"]:
            item["origins"].append(projected.origin)
    return [indexed[key] for key in sorted(indexed)]


@cache
def _checker_provenance():
    """Snapshot trusted code once per checking process, including import roots."""
    from .admission import ADMITTED_IMPORT_ROOTS

    root = Path(__file__).resolve().parent.parent
    # Static admission inspects trusted exports and constructor signatures;
    # those library bytes can change its answer just as the validator can.
    hashes, resolutions = {}, {}

    def record_file(path, external_key):
        path = path.resolve()
        key = path.relative_to(root).as_posix() if path.is_relative_to(root) else external_key
        hashes[key] = Sha256Digest.of_bytes(path.read_bytes()).value
        return key

    for package in sorted({"episode_builder", *ADMITTED_IMPORT_ROOTS}):
        spec = find_spec(package)
        if spec is None:
            resolutions[package] = {"status": "unresolved", "origin": None, "hash_keys": []}
            continue
        keys = set()
        for index, location in enumerate(spec.submodule_search_locations or ()):
            directory = Path(location)
            for path in sorted(directory.rglob("*.py")):
                keys.add(record_file(path, f"import:{package}/{index}/{path.relative_to(directory).as_posix()}"))
        if spec.origin not in {None, "built-in", "frozen"} and Path(spec.origin).is_file():
            keys.add(record_file(Path(spec.origin), f"import:{package}/{Path(spec.origin).name}"))
        status = "hashed" if keys else (
            spec.origin if spec.origin in {"built-in", "frozen"} else "unresolved"
        )
        resolutions[package] = {"status": status, "origin": spec.origin, "hash_keys": sorted(keys)}
    for path in sorted((root / "agent").glob("*contract*.py")):
        record_file(path, path.name)
    record_file(root / "agent" / "episode_blueprints.py", "agent/episode_blueprints.py")
    # Built-in/frozen roots have no standalone source file. Pin their interpreter
    # as well as the Python release, instead of pretending they were hashed.
    interpreter = Path(sys.executable).resolve()
    return {
        "checker_source_hashes": dict(sorted(hashes.items())),
        "checker_import_roots": resolutions,
        "checker_interpreter_hash": Sha256Digest.of_bytes(interpreter.read_bytes()).value,
    }


def materialization_handoff(store: BuildStore, receipt_id: OpaqueId | str) -> dict:
    """Evaluate the actual static checks on one exact persisted build candidate.

    This constructs evidence for publication, not a mutable read-time score.
    Library checks expose their actual predicates for future candidate checks.
    Each observation is tied to this candidate and the checking code's hashes.
    """
    return inspect_materialization(store, store.inspection_inputs_for_receipt(receipt_id))


def inspect_materialization(store: BuildStore, inputs) -> dict:
    """Check an exact candidate, including an architecture with no construction yet.

    A missing receipt means source admission has not happened. It remains a
    blocked observation, not a synthetic failed build or a successful check.
    """
    request, attempt, plan, receipt = (
        inputs.build_request, inputs.build_attempt, inputs.plan, inputs.receipt,
    )
    specification = project_materialized_specification(inputs)
    calls = model_call_evidence_for_attempt(store, attempt)
    from .source_inputs import read_source_inputs

    submitted = read_source_inputs(store, inputs)
    files, sources = _source_candidates(store, inputs, calls)
    candidate = _identified("materialization_candidate", {
        "receipt_ref": None if receipt is None else {
            "artifact_id": receipt.receipt_id.value,
            "content_hash": receipt.content_hash.value,
        },
        "plan_id": plan.plan_id.value,
        "workflow_hash": plan.workflow_hash.value,
        "model_call_evidence_ids": [call["evidence_id"] for call in calls],
        "files": files,
        "sources_by_episode": sources,
    })
    candidate_ref = _ref(candidate)
    requirements, checks, observations = [], [], []

    def check(definition, target, description, outcome, *, depends_on=()):
        # Stable across candidates and changing error wording; new approved
        # architecture means a new set of obligations, not new repair credit.
        obligation = {
            "workflow_hash": plan.workflow_hash.value,
            "target": target,
            "predicate": definition.component_id,
        }
        requirement_id = content_id("materialization_requirement", obligation).value
        check_id = content_id("materialization_check", obligation).value
        requirements.append({
            "requirement_id": requirement_id, "mandatory": True,
            "check_ids": [check_id], "description": description, **obligation,
        })
        checks.append({
            "check_id": check_id, "requirement_id": requirement_id,
            "definition_id": definition.definition_id,
            "target": target, "depends_on": list(depends_on),
        })
        observations.append({
            "check_id": check_id, "candidate_ref": candidate_ref,
            "definition_id": definition.definition_id, **outcome,
        })
        return requirement_id

    check(PLAN_CONSISTENCY, "/workflow_global/parts/materialization_plan",
          "Plan preserves approved authority, topology, and numeric selections",
          PLAN_CONSISTENCY.load()(request, attempt, plan))
    nodes = {node.local_id: node for node in plan.nodes}
    modules = {module.local_id: module for module in inputs.emitted_modules}
    module_names = tuple(node.module_name for node in plan.nodes)
    for episode in specification.episodes:
        local_id, target = episode.local_id, episode.stable_target
        node = nodes.get(local_id)
        plan_requirement = check(
            NODE_PLAN_CONSISTENCY, target + "/parts/node_plan",
            "Episode implementation plan and direct interfaces satisfy Builder checks",
            NODE_PLAN_CONSISTENCY.load()(request, plan, local_id),
        )
        raw_sources = sources.get(local_id, {}).get("raw_source_hashes", [])
        source = raw_sources[0] if len(raw_sources) == 1 else None
        # Emitter shape checks run before the host appends its declaration;
        # full module admission below checks the final post-attachment bytes.
        shape_outcome = _blocked("No unambiguous pre-declaration source was captured")
        if source is not None and node is not None:
            shape_outcome = SOURCE_SHAPE.load()(
                source=store.read_blob(source).decode("utf-8"),
                local_id=local_id, target_module_name=node.module_name,
                forbidden_module_names=tuple(name for name in module_names if name != node.module_name),
                is_root=node.parent_local_id is None,
            )
            shape_outcome = {**shape_outcome, "source_hash": source}
        source_requirement = check(
            SOURCE_SHAPE, target + "/parts/emitted_module",
            "Episode source satisfies syntax and emitter structure checks",
            shape_outcome, depends_on=(plan_requirement,),
        )
        module = modules.get(local_id)
        check(MODULE_ADMISSION, target + "/parts/admission",
              "Episode module passes static admission against its exact plan",
              _blocked("No completed emitted-module record is available") if module is None
              else MODULE_ADMISSION.load()(
                  request, plan, module,
                  environment_recipe=None if inputs.manifest is None else inputs.manifest.environment_recipe,
              ),
              depends_on=(plan_requirement, source_requirement))
    check(RECEIPT_MATERIALIZED, "/workflow_global/parts/outcome",
          "Entire approved workflow has a statically admitted materialization",
          _blocked("Source admission has not been performed") if receipt is None
          else RECEIPT_MATERIALIZED.load()(receipt),
          depends_on=tuple(item["requirement_id"] for item in requirements))

    achievement = requirement_satisfaction(
        requirements=requirements, observations=observations, candidate_ref=candidate_ref,
    )
    # Import existing achievement as the starting state, not work the Refiner
    # has newly earned. Later callers retain this union across all candidates.
    baseline = requirement_satisfaction(
        requirements=requirements, observations=observations, candidate_ref=candidate_ref,
        credited_requirement_ids=achievement["current_satisfied_requirement_ids"],
        previous_satisfied_requirement_ids=achievement["current_satisfied_requirement_ids"],
    )
    parts = [
        {"target": part.stable_target, "content_hash": part.content_hash.value,
         "present": part.value is not None}
        for part in (*specification.workflow_global,
                     *(part for episode in specification.episodes for part in episode.parts))
    ]
    edges = {edge.child_local_id: edge.as_record() for edge in plan.edges}
    dependencies = [
        {"parent_local_id": episode.workflow_parent_local_id,
         "child_local_id": episode.local_id,
         "accepted_edge_plan": edges.get(episode.local_id)}
        for episode in request.frozen_workflow.workflow.episodes
        if episode.workflow_parent_local_id is not None
    ]
    return _identified("materialization_handoff", {
        "scope": "initial_materialization_static_evidence",
        "build_request_id": request.build_request_id.value,
        "build_attempt_id": attempt.build_attempt_id.value,
        "receipt_id": None if receipt is None else receipt.receipt_id.value,
        "status": "not_materialized" if receipt is None else receipt.status,
        "candidate": candidate,
        "materialized_specification": specification.as_record(),
        "parts": parts,
        "episode_dependencies": dependencies,
        "model_calls": list(calls),
        **({"submitted_materialization": submitted["materialization"]}
           if submitted is not None else {}),
        "diagnostics": _diagnostic_index(specification),
        "requirements": requirements,
        "checks": checks,
        "observations": observations,
        "progress": baseline,
        "check_definitions": [definition.as_record() for definition in materialization_check_library.functions()],
        "progress_definition": REQUIREMENT_SATISFACTION.as_record(),
        **_checker_provenance(),
        "checker_python": list(sys.version_info[:3]),
        "limitations": [
            "Static materialization evidence does not establish runtime or scientific correctness.",
            "Missing source and blocked checks grant no requirement satisfaction.",
            "Captured model text and source are untrusted data, never steering authority.",
            "Reference-dependent plan checks need the exact resolved reference context; absence is blocked.",
        ],
    })


def read_materialization_handoff(store: BuildStore, receipt_id: OpaqueId | str) -> dict:
    """Load immutable recorded outcomes without running today's validators."""
    receipt = store.read_receipt(receipt_id)

    def validate(record):
        payload = {key: value for key, value in record.items()
                   if key not in {"artifact_id", "content_hash"}}
        if _identified("materialization_handoff", payload) != record:
            raise ValueError("materialization handoff identity is stale")
        if record["candidate"]["receipt_ref"] != {
            "artifact_id": receipt.receipt_id.value, "content_hash": receipt.content_hash.value,
        }:
            raise ValueError("materialization handoff names another receipt")
        for digest in record["candidate"]["files"].values():
            store.read_blob(digest)
        return dict(record)

    return store._read_record("materialization_handoffs", receipt.receipt_id, validate)


def publish_materialization_handoff(store: BuildStore, receipt_id: OpaqueId | str) -> dict:
    """Publish once after the receipt; repeated reads keep the original checks."""
    receipt = store.read_receipt(receipt_id)
    path = store._record_path("materialization_handoffs", receipt.receipt_id)
    if path.exists():
        return read_materialization_handoff(store, receipt.receipt_id)
    record = materialization_handoff(store, receipt.receipt_id)
    store._put_record("materialization_handoffs", receipt.receipt_id, record)
    return read_materialization_handoff(store, receipt.receipt_id)
