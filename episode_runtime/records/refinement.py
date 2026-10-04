"""Bounded refinement history from the existing campaign index.

Queries expose admitted index entries, not arbitrary stored model proposals.
One transaction supplies the assignment scope, current applicability and source
head. A changed head requires a fresh page instead of silently mixing states.
"""

from collections.abc import Mapping

from agent.episode_contracts import OpaqueId
from iterative_episode_refiner.campaign_store import CampaignView
from iterative_episode_refiner.records import Ref
from iterative_episode_refiner.reports import check_result


def _selection(view, assignment, collection, requirement_key=None):
    scope = tuple(assignment.body["scope_requirement_keys"])
    if requirement_key is not None:
        if requirement_key not in scope:
            raise ValueError("history requirement is outside the assigned scope")
        scope = (requirement_key,)
    marks = ",".join("?" for _ in scope)
    if collection == "controls":
        return (
            " JOIN artifacts b ON b.artifact_id = COALESCE("
            "json_extract(a.record_json, '$.body.control_run_ref.artifact_id'), a.artifact_id) "
            "JOIN artifacts g ON g.artifact_id = json_extract(b.record_json, '$.body.grounding_ref.artifact_id')",
            f"json_extract(g.record_json, '$.requirement_key') IN ({marks})",
            scope,
        )
    if collection == "observations":
        joins = (
            " JOIN refinement_index ci ON ci.campaign_id = i.campaign_id "
            "AND ci.collection = 'check' AND ci.item_key = "
            "json_extract(a.record_json, '$.body.check_key') "
            "JOIN artifacts c ON c.artifact_id = ci.record_id"
        )
        return (
            joins,
            f"json_extract(c.record_json, '$.body.requirement_key') IN ({marks})",
            scope,
        )
    if collection == "reports":
        return (
            "",
            (
                "(json_extract(a.record_json, '$.body.assignment_ref.artifact_id') = ? OR "
                "EXISTS (SELECT 1 FROM artifacts child WHERE child.artifact_id = "
                "json_extract(a.record_json, '$.body.assignment_ref.artifact_id') AND "
                "child.duet_id = a.duet_id AND "
                "json_extract(child.record_json, '$.body.parent_assignment_ref.artifact_id') = ?))"
            ),
            (assignment.artifact_id.value, assignment.artifact_id.value),
        )
    return (
        "",
        (
            "EXISTS (SELECT 1 FROM json_each(a.record_json, '$.body.requirement_keys') "
            f"WHERE value IN ({marks}))"
        ),
        scope,
    )


def _observation(view, entry):
    record = entry.record
    check = view.entry("check", record.body["check_key"])
    present = view.connection.execute(
        "SELECT item_key FROM refinement_index WHERE campaign_id = ? "
        "AND collection = 'check_state' AND item_key = ?",
        (view.campaign_id.value, check.key),
    ).fetchone()
    current = None if present is None else view.entry("check_state", check.key)
    return {
        "observation_ref": record.ref.as_record(),
        "invocation_id": record.invocation_id.value,
        "sequence": entry.sequence,
        "check_key": check.key,
        "current_observation_ref": None
        if current is None
        else current.record.ref.as_record(),
        "current_status": "not_run" if current is None else current.status,
        "is_current_observation": current is not None
        and record.ref == current.record.ref,
        "test_result": check_result(view, check.record, entry),
    }


def _report(view, entry):
    record = entry.record
    body = record.as_record()["body"]
    return {
        "report_ref": record.ref.as_record(),
        "invocation_id": record.invocation_id.value,
        "source_head_ref": body["complete_index_ref"],
        **{
            key: body[key]
            for key in (
                "role",
                "scope_requirement_keys",
                "selected_candidate_ref",
                "determinations",
                "unresolved_requirement_keys",
                "conflict_refs",
                "termination",
                "continuation_ref",
            )
        },
    }


def _control(view, entry):
    """Project the existing control admission and shared measured experiment."""
    from .experiments import record_id
    from .outcomes import RequirementOutcome
    from episode_runtime.testing.contracts import ExperimentSpec

    observation = entry.record if entry.status == "observed" else None
    binding = entry.record if observation is None else view.read(
        Ref.from_record(observation.body["control_run_ref"]), "measure_control_run"
    )
    grounding = view.data(Ref.from_record(binding.body["grounding_ref"]))
    result = {
        "kind": "measure_adequacy_control",
        "control_run_ref": binding.ref.as_record(),
        "observation_ref": None if observation is None else observation.ref.as_record(),
        "invocation_id": binding.invocation_id.value,
        "sequence": entry.sequence,
        "status": entry.status,
        "requirement_key": grounding["requirement_key"],
        "proposal_ref": binding.body["proposal_ref"],
        "control_ref": binding.body["control_ref"],
        "gap": binding.body["gap"],
        "checker_predicate_outcome": None if observation is None else observation.body["outcome"],
        "execution_ref": None if observation is None else observation.body["execution_ref"],
        "experiment_id": None,
        "measurement_ref": None,
        "outcome": None,
        "limitations": ["This tests one measuring mechanism's grounded behavior, not repaired-target acceptance or complete measure adequacy."],
    }
    reference = binding.body.get("experiment_ref")
    if reference is None:
        return result
    dispatch = view.data(Ref.from_record(reference))
    experiment_id = ExperimentSpec.from_record(dispatch["spec"]).experiment_id
    result["experiment_id"] = experiment_id
    row = view.connection.execute(
        "SELECT artifact_id, content_hash FROM artifacts WHERE artifact_id = ? AND duet_id = ?",
        (record_id("measurement", experiment_id=experiment_id), view.head["duet_id"]),
    ).fetchone()
    if row is not None:
        measured = Ref.from_record(dict(row))
        measurement = view.data(measured)
        result["measurement_ref"] = measured.as_record()
        result["outcome"] = RequirementOutcome.model_validate(measurement["outcomes"][0]).model_dump(mode="json")
    return result


def _conflict(view, entry, assignment):
    record = entry.record
    body = record.as_record()["body"]
    scope = set(assignment.body["scope_requirement_keys"])
    observations = []
    candidates = {}
    for reference in body["observation_refs"]:
        observation = view.read(Ref.from_record(reference), "observation")
        check = view.entry("check", observation.body["check_key"]).record
        if check.body["requirement_key"] in scope:
            observations.append(reference)
            admitted = view.entry("observation", observation.artifact_id.value)
            if admitted.record.ref != observation.ref:
                raise ValueError(
                    "conflict observation differs from its admitted identity"
                )
            result = _observation(view, admitted)
            candidate = result["test_result"]["candidate_ref"]
            candidates.setdefault(
                candidate["artifact_id"],
                {
                    "candidate_ref": candidate,
                    "observations": [],
                },
            )["observations"].append(result)
    return {
        "conflict_ref": record.ref.as_record(),
        "kind": body["kind"],
        "state": entry.status,
        "requirement_keys": sorted(scope.intersection(body["requirement_keys"])),
        "scope_owner_invocation_id": body["scope_owner_invocation_id"],
        "observation_refs": observations,
        "candidate_results": list(candidates.values()),
        "withheld_observation_count": len(body["observation_refs"]) - len(observations),
        "resolution_ref": body["resolution_ref"],
    }


def refinement_history(artifacts, *, duet_id, query, view=None):
    if view is None:
        with artifacts.transaction() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'refinement_campaign_heads'"
                ).fetchone()
                is None
            ):
                raise ValueError(
                    "no refinement campaigns have been recorded in this store"
                )
            return refinement_history(
                artifacts,
                duet_id=duet_id,
                query=query,
                view=CampaignView(connection, OpaqueId(query.campaign_id)),
            )
    if view.campaign_id.value != query.campaign_id or view.head["duet_id"] != duet_id:
        raise ValueError("refinement history belongs to another campaign or owner")
    head = (
        view.read(view.head["latest_commit_id"]).ref
        if view.head["latest_commit_id"]
        else view.contract.ref
    )
    if (
        query.campaign_head_ref is not None
        and query.campaign_head_ref.model_dump() != head.as_record()
    ):
        raise ValueError(
            "campaign changed while paging; start a fresh history query without after or campaign_head_ref"
        )
    if query.after is not None and query.campaign_head_ref is None:
        raise ValueError(
            "refinement history pagination requires the returned campaign_head_ref"
        )
    assignment = view.entry("invocation", query.invocation_id).record
    collection = query.refinement_collection or "observations"
    index_collection = {
        "observations": "observation",
        "reports": "report",
        "conflicts": "conflict",
        "controls": "measure_control",
    }[collection]
    joins, selected, selected_values = _selection(
        view, assignment, collection, query.requirement_key
    )
    terms = ["i.campaign_id = ?", "i.collection = ?", "a.duet_id = ?", selected]
    values = [query.campaign_id, index_collection, duet_id, *selected_values]
    if query.conflict_status is not None:
        terms.append("i.status = ?")
        values.append(query.conflict_status)
    source = (
        " FROM refinement_index i JOIN artifacts a ON a.artifact_id = i.record_id"
        + joins
    )
    if query.after is not None:
        cursor = view.connection.execute(
            "SELECT i.sequence, i.item_key"
            + source
            + " WHERE "
            + " AND ".join(terms)
            + " AND i.item_key = ?",
            (*values, query.after),
        ).fetchone()
        if cursor is None:
            raise ValueError(
                "refinement history cursor is outside the assigned scope or collection"
            )
        terms.append("(i.sequence < ? OR (i.sequence = ? AND i.item_key < ?))")
        values.extend((cursor["sequence"], cursor["sequence"], cursor["item_key"]))
    rows = view.connection.execute(
        "SELECT i.item_key"
        + source
        + " WHERE "
        + " AND ".join(terms)
        + " ORDER BY i.sequence DESC, i.item_key DESC LIMIT ?",
        (*values, query.limit + 1),
    ).fetchall()
    selected_query = {
        **query.model_dump(mode="json"),
        "refinement_collection": collection,
        "campaign_head_ref": head.as_record(),
    }
    projection = {
        "observations": _observation,
        "reports": _report,
        "conflicts": lambda state, entry: _conflict(state, entry, assignment),
        "controls": _control,
    }[collection]
    cursor = rows[query.limit - 1]["item_key"] if len(rows) > query.limit else None
    result = {
        "schema_version": 1,
        "record_type": f"refinement_{collection}",
        "query": selected_query,
        "assignment_ref": assignment.ref.as_record(),
        "current_candidate_ref": view.candidate.ref.as_record(),
        "campaign_head_ref": head.as_record(),
        "campaign_sequence": view.head["sequence"],
        "items": [
            projection(view, view.entry(index_collection, row["item_key"]))
            for row in rows[: query.limit]
        ],
        "next_cursor": cursor,
        "next_query": None if cursor is None else {**selected_query, "after": cursor},
        "related_queries": {
            name: {
                **selected_query,
                "refinement_collection": name,
                "after": None,
                "requirement_key": None if name == "reports" else query.requirement_key,
                "conflict_status": query.conflict_status
                if name == "conflicts"
                else None,
            }
            for name in ("observations", "reports", "conflicts", "controls")
            if name != collection
        },
        "limitations": [
            "Historical test outcomes do not grant current acceptance or credit. Inspect current_status and the original tested candidate.",
            "Reports retain their recorded source head and may predate the current campaign. Only own/direct-child reports and assigned requirements are visible.",
            "A changed campaign head requires a fresh query. History retrieval never resumes execution or replays evidence.",
        ],
    }
    if collection == "observations":
        # The stock refiner receives this first page before choosing its next
        # action. A cycle must be visible there, not only behind a query the
        # model may never request. Supporting history stays bounded and scoped.
        result["conflicts"] = refinement_history(
            artifacts,
            duet_id=duet_id,
            view=view,
            query=query.model_copy(
                update={
                    "refinement_collection": "conflicts",
                    "after": None,
                    "limit": 3,
                    "campaign_head_ref": None,
                    "conflict_status": "decision_required",
                }
            ),
        )
        result["controls"] = refinement_history(
            artifacts, duet_id=duet_id, view=view,
            query=query.model_copy(update={
                "refinement_collection": "controls", "after": None,
                "limit": 3, "campaign_head_ref": None, "conflict_status": None,
            }),
        )
    return result


def assigned_history(view, invocation_id, query=None):
    """Bind a worker's query to its host-selected campaign and assignment."""
    from .catalog import HistoryQuery

    owner = {
        "kind": "refinement",
        "campaign_id": view.campaign_id.value,
        "invocation_id": invocation_id.value,
    }
    if query is not None and not isinstance(query, Mapping):
        raise ValueError("test_history_query must be a structured history query")
    value = {} if query is None else dict(query)
    if any(value.get(key, expected) != expected for key, expected in owner.items()):
        raise ValueError(
            "history query cannot replace the host-bound refinement assignment"
        )
    return refinement_history(
        None,
        duet_id=view.head["duet_id"],
        query=HistoryQuery.model_validate({**value, **owner}),
        view=view,
    )
