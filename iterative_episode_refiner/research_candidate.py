"""Read one approved Target Workflow node from the campaign's current candidate.

Question and Support inspect a named Episode's design, interfaces or source as
evidence. The host resolves the immutable records and mapped source path; the
request supplies neither a filesystem path nor an arbitrary artifact identity.
Reading another approved node supports sibling-interface questions without
granting source, plan or architecture editing authority.
"""

from hashlib import sha256

from agent.duet_contracts import FrozenDuetWorkflow, canonical_json
from episode_builder._contract_chain import WorkflowMaterializationPlan
from function_library.epistemic_contract import exact
from function_library.models import _thaw_json

from .materialization_edits import source_paths, stored_plan
from .records import Ref
from .research_sources import _clean_text


def _current(view):
    candidate = view.candidate
    contract = view.contract
    frozen = FrozenDuetWorkflow.from_record(view.data(
        Ref.from_record(contract.body["target_workflow_ref"])
    ))
    if frozen.duet_id.value != contract.body["duet_id"]:
        raise ValueError("research architecture belongs to another Duet")
    workflow = frozen.workflow
    plan = WorkflowMaterializationPlan.from_record(
        _thaw_json(stored_plan(view, candidate))
    )
    if plan.workflow_hash != workflow.workflow_hash:
        raise ValueError("research materialization differs from the approved Target Workflow")
    return candidate, workflow, plan, source_paths(workflow, plan)


def catalog(view):
    """Advertise available node addresses, without expanding their contents."""
    candidate, workflow, plan, paths = _current(view)
    materialized = {node.local_id for node in plan.nodes}
    return [{
        "local_id": node.local_id,
        "materialized": node.local_id in materialized,
        "source_available": paths[node.local_id] in candidate.body["files"],
    } for node in workflow.episodes]


def read(evidence, view, arguments, secrets):
    """Retrieve exact current evidence through the ordinary research source shape.

    Architecture is the approved node plus touching repeatable-call declarations.
    Materialization is its current node plan plus touching direct/repeatable edges.
    Source is the mapped candidate module's bytes, not an executed/imported module.
    Provenance stays in the source handle and the host's persisted source record;
    the parent receives only its requested synthesis through the existing report.
    """
    exact(arguments, {"local_id", "section"}, "candidate research request")
    local_id, section = arguments["local_id"], arguments["section"]
    if not isinstance(local_id, str) or not local_id.strip():
        raise ValueError("candidate research requires an approved Episode local_id")
    if section not in {"architecture", "materialization", "source"}:
        raise ValueError("candidate section must be architecture, materialization or source")
    candidate, workflow, plan, paths = _current(view)
    designs = {node.local_id: node for node in workflow.episodes}
    if local_id not in designs:
        return {
            "success": False, "sources": [],
            "error": "The requested Episode is outside this campaign's approved Target Workflow.",
        }
    nodes = {node.local_id: node for node in plan.nodes}
    if section == "materialization" and local_id not in nodes:
        return {
            "success": False, "sources": [],
            "error": f"Episode {local_id} has no materialization plan in the current candidate.",
        }
    if section == "source" and paths[local_id] not in candidate.body["files"]:
        return {
            "success": False, "sources": [],
            "error": f"Episode {local_id} has no source module in the current candidate.",
        }
    if section == "source":
        digest = candidate.body["files"][paths[local_id]]
        content = evidence.builds.read_blob(digest).decode("utf-8")
    elif section == "architecture":
        content = canonical_json({
            "episode": designs[local_id].as_record(),
            "repeatable_calls": [call.as_record() for call in workflow.repeatable_calls
                                 if local_id in (call.caller_local_id, call.callee_template_local_id)],
        })
    else:
        content = canonical_json({
            "node": nodes[local_id].as_record(),
            "edges": [edge.as_record() for edge in plan.all_edges
                      if local_id in (edge.parent_local_id, edge.child_local_id)],
        })
    clean = _clean_text(content, secrets, source_code=section == "source")
    return {"success": True, "sources": [{
        "source_id": f"candidate:{candidate.artifact_id.value}:{section}:{local_id}",
        "kind": "candidate",
        "title": f"Target Workflow Episode {local_id}: {section}",
        "url": None, "path": None,
        "content": clean,
        "content_hash": sha256(clean.encode("utf-8")).hexdigest(),
        "truncated": False,
        "redacted": clean != content,
    }], "error": None}
