"""Bounded invocation/unit discovery at an exact indexed audit prefix."""

from typing import Annotated, Literal

from pydantic import Field

from .index import RunRecordIndex, read_fact
from .facts import unit_prefix
from .runs import EvidenceReference, RecordModel


class AuditReference(RecordModel):
    run_id: str
    event_id: str
    content_hash: str


class InventoryQuery(RecordModel):
    kind: Literal["invocations", "units"] = "invocations"
    episode_id: str | None = None
    through_event_ref: AuditReference | None = None
    after: int | None = Field(default=None, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class RunSource(RecordModel):
    kind: Literal["run"]
    run_id: str


class ExperimentSource(RecordModel):
    kind: Literal["experiment"]
    experiment_id: str


class RecordingSource(RecordModel):
    kind: Literal["recording"]
    recording_ref: EvidenceReference


class InventoryRequest(RecordModel):
    source: Annotated[RunSource | ExperimentSource | RecordingSource, Field(discriminator="kind")]
    query: InventoryQuery


def _reference(fact):
    return {
        "run_id": fact.run_id, "event_id": fact.event.event_id,
        "content_hash": fact.event.content_hash,
    }


def _last(connection, registration, episode_id, kind, through):
    row = connection.execute(
        "SELECT * FROM facts WHERE episode_id IS ? AND kind=? AND sequence<=? ORDER BY sequence DESC LIMIT 1",
        (episode_id, kind, through),
    ).fetchone()
    return None if row is None else read_fact(row, registration)


_COUNTS = {
    "units": "unit_completed",
    "model_requests": "model_requested", "model_responses": "model_responded",
    "http_requests": "http_requested", "http_responses": "http_responded",
    "learning_commits": "learning_committed",
}


def _invocation(connection, registration, fact, through):
    counts = {}
    for name, kind in _COUNTS.items():
        last = _last(connection, registration, fact.episode_id, kind, through)
        counts[name] = 0 if last is None else last.ordinal + 1
    completion = _last(connection, registration, fact.episode_id, "episode_completed", through)
    start = _last(connection, registration, fact.episode_id, "episode_started", through)
    detail = fact.detail
    complete_entry = all((
        detail["episode_path"], detail["request_hash"], detail["has_goal_view"],
        detail["goal_state_id"], detail["initial_goal_state_id"],
    ))
    return {
        "episode_id": fact.episode_id, "event_ref": _reference(fact),
        "origin": fact.origin, **detail, "counts": counts,
        "repeated_identity": start is not None and start.ordinal > 0,
        "completion": None if completion is None else {
            **completion.detail, "event_ref": _reference(completion), "origin": completion.origin,
        },
        "entry_context": "missing" if not complete_entry else "requires_boundary_validation",
        "state_restoration": "not_needed_for_initial_entry" if detail["initial_state_reproducible"] is True
        else "missing_state_identity" if detail["initial_state_reproducible"] is None else "required_not_implemented",
    }


def _cutoff(connection, registration, reference):
    if reference.run_id != registration.run_id.value:
        raise ValueError("inventory prefix belongs to another Run")
    row = connection.execute("SELECT * FROM facts WHERE event_id=?", (reference.event_id,)).fetchone()
    if row is None:
        raise ValueError("inventory prefix is not present in the maintained index; refresh or select an available prefix")
    fact = read_fact(row, registration)
    if _reference(fact) != reference.model_dump(mode="json"):
        raise ValueError("inventory prefix hash differs from its recorded identity")
    return fact.event.sequence


def _unit(connection, registration, fact):
    before = fact.event.sequence - 1
    return {
        "episode_id": fact.episode_id, "event_ref": _reference(fact),
        "origin": fact.origin, **fact.detail,
        "reconstruction_prefix": unit_prefix(
            fact,
            invocation_start=_last(connection, registration, fact.episode_id, "episode_started", before),
            previous_unit=_last(connection, registration, fact.episode_id, "unit_completed", before),
        ),
    }


def inventory(store, run_id, query, *, selected_episode_ids=None, through_event_ref=None):
    """Host-only selectors bound a recording; caller query cannot broaden them."""
    query = InventoryQuery.model_validate(query)
    registration = store.read_registration(run_id)
    index = RunRecordIndex(store)
    with index.connection(run_id) as connection:
        summary = index._load(connection, run_id)
        view = index.inspect_record(registration, summary)
        result = {
            "schema_version": 1, "kind": query.kind, "run_id": run_id.value,
            "registration_hash": registration.registration_hash.value,
            "index_status": view["index_status"], "required_action": view["required_action"],
            "items": [], "next_query": None,
            "limitations": [
                "These are compact recorded facts, not verified behavioral outcomes, acceptance or credit.",
                "Entry context and response counts are discovery leads; boundary validation and experiment preview are required.",
                "No prompts, response bodies, controller state or resumable checkpoint are returned.",
            ],
        }
        if view["index_status"] in {"unavailable", "behind"}:
            return result
        if summary.through_event is None:
            return {**result, "through_event_ref": None}
        current_ref = AuditReference(run_id=run_id.value, **summary.through_event.model_dump(exclude={"sequence"}))
        ceiling_ref = current_ref if through_event_ref is None else AuditReference.model_validate(through_event_ref)
        ceiling = _cutoff(connection, registration, ceiling_ref)
        reference = query.through_event_ref or ceiling_ref
        cutoff = _cutoff(connection, registration, reference)
        if cutoff > ceiling or (query.after is not None and query.after > cutoff):
            raise ValueError("inventory query exceeds its selected recording prefix")
        terms = ["kind=?", "sequence>?", "sequence<=?"]
        parameters = [
            "episode_started" if query.kind == "invocations" else "unit_completed",
            -1 if query.after is None else query.after, cutoff,
        ]
        if selected_episode_ids is not None:
            if query.episode_id is not None and query.episode_id not in selected_episode_ids:
                raise ValueError("inventory query names an invocation outside its recording selector")
            if not selected_episode_ids:
                return {**result, "through_event_ref": reference.model_dump(mode="json")}
            terms.append("episode_id IN (" + ",".join("?" for _ in selected_episode_ids) + ")")
            parameters.extend(selected_episode_ids)
        if query.episode_id is not None:
            terms.append("episode_id=?")
            parameters.append(query.episode_id)
        rows = connection.execute(
            "SELECT * FROM facts WHERE " + " AND ".join(terms) + " ORDER BY sequence LIMIT ?",
            (*parameters, query.limit + 1),
        ).fetchall()
        facts = [read_fact(row, registration) for row in rows[:query.limit]]
        result["items"] = [
            _invocation(connection, registration, fact, cutoff) if query.kind == "invocations"
            else _unit(connection, registration, fact)
            for fact in facts
        ]
        result["through_event_ref"] = reference.model_dump(mode="json")
        if len(rows) > query.limit:
            result["next_query"] = {
                **query.model_dump(mode="json"), "after": facts[-1].event.sequence,
                "through_event_ref": reference.model_dump(mode="json"),
            }
        return result
