"""Read-only learning baselines for independently scoped unit experiments.

Original records stay in their original journal. The host projects operative
scope and equivalence into the new invocation, retaining original evidence and
record identities for provenance and revision selectors. Nothing is re-admitted
or credited by this projection. Both ledger and publication validation use it.
"""

from dataclasses import dataclass
from typing import Mapping

from agent.episode_contracts import OpaqueId
from function_library.epistemic import default_components
from function_library.epistemic_admission import _hash, scope_record
from function_library.epistemic_contract import EpistemicContract, exact
from function_library.epistemic_schemas import ArtifactEnvelope, canonical, identity
from function_library.models import _freeze_json, _thaw_json
from method_loop.identities import UnitRef

from .contracts import RunEventKind, RunEventOrigin


@dataclass(frozen=True)
class LearningBaseline:
    reference: Mapping
    policy: Mapping
    state: Mapping
    evidence: Mapping
    history: tuple[Mapping, ...]

    @property
    def inherited_credit(self):
        return sum(row["receipt"]["measurement"]["realized_yield"] for row in self.history)


def _source_history(runs, source, unit_ref, selected_event_ref):
    from .testing_harness.recordings import event_reference, read_recording
    from .testing_harness.units import verified_unit_prefix
    from .learning_integrity import validate_learning_commit
    from .store import RunStoreNotFound

    unit = UnitRef.from_record(unit_ref)
    if source.resume_from is not None or source.execution_scope is not None:
        raise ValueError("saved learning currently requires an original whole-Run recording, not a continued or scoped attempt")
    # A fixed prefix is immutable even while a Run continues, but this initial
    # route deliberately requires terminal publication and complete ownership.
    try:
        events = runs.read_audit_log(source.run_id)
    except RunStoreNotFound as exc:
        raise ValueError(
            "saved learning requires terminal source evidence; inspect the existing Run rather than restarting it"
        ) from exc
    selected = next((event for event in events if event_reference(event) == selected_event_ref), None)
    if selected is None or canonical(selected.payload.get("unit_ref")) != canonical(unit_ref):
        raise ValueError("saved learning selection differs from its committed UnitRef")
    prefix = verified_unit_prefix(runs, source, selected_event_ref)
    if prefix["status"] != "located" or unit.unit_index == 0:
        raise ValueError("saved learning needs a located later-unit starting boundary")
    recording = read_recording(runs, source.run_id, through_event_ref=prefix["through_event_ref"])
    if recording["gaps"]:
        raise ValueError("saved learning prefix contains incomplete host or external exchanges")
    cutoff = next(event.sequence for event in events if event_reference(event) == prefix["through_event_ref"])
    events = events[:cutoff + 1]
    owned = [event for event in events if event.episode_id == OpaqueId(unit.episode_id)]
    starts = [event for event in owned if event.kind is RunEventKind.EPISODE_STARTED]
    units = [event for event in owned if event.kind is RunEventKind.UNIT_COMPLETED]
    commits = [event for event in owned if event.kind is RunEventKind.LEARNING_COMMITTED]
    policies = [event for event in owned if event.kind is RunEventKind.LEARNING_OPENED]
    if len(starts) != 1 or len(policies) != 1 or len(units) != unit.unit_index or len(commits) != unit.unit_index:
        raise ValueError("saved learning requires complete contiguous unit and learning history")
    if policies[0].origin is not RunEventOrigin.HOST_LEARNING:
        raise ValueError("saved learning policy is not host admitted")
    policy = _thaw_json(policies[0].payload)
    contract = EpistemicContract.from_record(policy["contract"])
    if contract.scope_tier != "episode" or canonical(contract.components) != canonical(default_components()):
        raise ValueError("saved learning restoration supports Episode-local stock epistemic schemas and functions only")
    for ordinal, (observed, committed) in enumerate(zip(units, commits)):
        receipt = committed.payload["receipt"]
        if (
            observed.origin is not RunEventOrigin.WORKER
            or observed.payload.get("unit_ref") != UnitRef(unit.episode_id, ordinal).as_record()
            or observed.payload.get("unit_label") != f"reasoning-{ordinal}"
            or observed.payload.get("epoch") != "epistemic-v1"
            or observed.payload.get("episode_update") is not None
            or observed.payload.get("goal_result") is not None
            or canonical(observed.payload.get("controller_input")) != canonical(receipt)
            or canonical(observed.payload.get("controller_step")) != canonical(receipt)
            or receipt["ordinal"] != ordinal
            or receipt["terminal_state"] != "continuing" or receipt["stop"]
            or committed.sequence >= observed.sequence
            or (ordinal and units[ordinal - 1].sequence >= committed.sequence)
        ):
            raise ValueError("saved learning does not describe a closed continuing stock reasoning boundary")
        validate_learning_commit(
            events=events[:committed.sequence], origin=committed.origin,
            episode_id=committed.episode_id, payload=committed.payload,
        )
    if any(event.kind in {RunEventKind.LEARNING_SELECTED, RunEventKind.LEARNING_ATTEMPT}
           and event.payload.get("ordinal", unit.unit_index - 1) >= unit.unit_index
           for event in owned):
        raise ValueError("saved learning boundary contains unfinished next-unit work")
    original_scope = scope_record(contract, episode_id=unit.episode_id, workflow_id=source.workflow_id.value)
    evidence = {
        event.payload["artifact"]["artifact_id"]: _thaw_json(event.payload["artifact"])
        for event in events if event.kind is RunEventKind.LEARNING_EVIDENCE
        and event.origin is RunEventOrigin.HOST_LEARNING
        and canonical(event.payload.get("scope")) == canonical(original_scope)
    }
    expected_evidence = [ArtifactEnvelope(
        schema_id="openchia.approved-evidence", schema_version=1,
        run_id=source.logical_run_id.value, episode_id=original_scope["key"],
        unit_id="approved-input", producer_call_id="exact-human-approved-contract",
        evidence_refs=(), body=value,
    ).as_record() for value in contract.evidence]
    if canonical(evidence) != canonical({value["artifact_id"]: value for value in expected_evidence}):
        raise ValueError("saved learning evidence differs from the frozen approved sources")
    state = [
        _thaw_json(record) for record in commits[-1].payload["state"]["records"]
        if canonical(record["scope"]) == canonical(original_scope)
    ]
    if any(not set(record["evidence_refs"]) <= evidence.keys() for record in state):
        raise ValueError("saved learning records lack their authorized evidence")
    return prefix, policy, state, evidence, commits


def baseline_selector(runs, source, *, unit_ref, selected_event_ref, source_admission):
    """Freeze references and the worker's one retained receipt, not a second log."""
    prefix, _, _, _, commits = _source_history(runs, source, unit_ref, selected_event_ref)
    return _selector(source, prefix, commits, source_admission)


def _selector(source, prefix, commits, source_admission):
    return {
        "schema_version": 1,
        "source_registration_ref": {"run_id": source.run_id.value, "content_hash": source.registration_hash.value},
        "through_event_ref": prefix["through_event_ref"],
        "completed_units": len(commits),
        "controller_state": _thaw_json(commits[-1].payload["receipt"]),
        "source_admission": source_admission,
    }


def load_learning_baseline(runs, registration, episode_id):
    """Independently derive the starting state; never trust a supplied checkpoint."""
    scope = registration.execution_scope
    selector = getattr(scope, "learning_baseline", None)
    if selector is None:
        return None
    target = scope.target_ref(registration.logical_run_id.value)
    if episode_id is None or episode_id.value != target.episode_id:
        raise ValueError("learning baseline is limited to the selected unit invocation")
    exact(selector, {
        "schema_version", "source_registration_ref", "through_event_ref",
        "completed_units", "controller_state", "source_admission",
    }, "learning baseline")
    source = runs.read_registration(OpaqueId(selector["source_registration_ref"]["run_id"]))
    if (
        selector["schema_version"] != 1
        or selector["source_registration_ref"]["content_hash"] != source.registration_hash.value
        or source.run_id.value != scope.boundary["source_run_id"]
        or source.duet_id != registration.duet_id
        or source.workflow_hash != registration.workflow_hash
        or source.manifest_id != registration.manifest_id
        or source.manifest_hash != registration.manifest_hash
        or source.runtime_identity != registration.runtime_identity
    ):
        raise ValueError("learning baseline changes its owner, frozen code or runtime")
    admission = selector["source_admission"]
    if (
        admission.get("kind") != "stock_reasoning_unit_source"
        or admission.get("schema_version") != 1
        or admission.get("entry_local_id") != scope.entry_local_id
        or admission.get("manifest_ref") != {
            "artifact_id": source.manifest_id.value, "content_hash": source.manifest_hash.value,
        }
    ):
        raise ValueError("learning baseline lacks its exact source-shape admission")
    prefix, policy, records, evidence, commits = _source_history(runs, source, scope.unit_ref, scope.unit_event_ref)
    expected = _selector(source, prefix, commits, _thaw_json(admission))
    if canonical(selector) != canonical(expected):
        raise ValueError("learning baseline differs from its committed starting boundary")
    contract = EpistemicContract.from_record(policy["contract"])
    target_scope = scope_record(contract, episode_id=episode_id.value, workflow_id=registration.workflow_id.value)
    equivalences = {}
    for record in records:
        if record["kind"] == "lesson":
            key = identity("lesson", {
                "scope": target_scope, "action_class": record["body"]["action_class"],
                "action_inputs": record["body"]["action_inputs"],
            })
        elif record["kind"] == "entity":
            key = identity("entity", {"scope": target_scope, "anchors": sorted({
                evidence[ref]["content_hash"] for ref in record["evidence_refs"]
            })})
        else:
            raise ValueError("saved learning contains an unsupported record schema")
        old = record.get("equivalence_key", record["record_id"])
        if old in equivalences and equivalences[old] != key:
            raise ValueError("saved equivalence cannot be projected consistently")
        equivalences[old] = key
        record.update(scope=target_scope, equivalence_key=key)
        record["content_hash"] = _hash(record)
    history = []
    for event in commits:
        value = _thaw_json(event.payload)
        for field in ("baseline_ids", "observation_ids"):
            if not set(value[field]) <= equivalences.keys():
                raise ValueError("saved controller history references unavailable knowledge")
            value[field] = sorted(equivalences[key] for key in value[field])
        # This is a historical numerical input, not a newly published commit.
        history.append(_freeze_json({
            key: value[key] for key in ("unit_id", "baseline_ids", "observation_ids", "receipt")
        }, "historical observation"))
    return LearningBaseline(
        reference=_freeze_json(selector, "baseline reference"),
        policy=_freeze_json(policy, "baseline policy"),
        state=_freeze_json({"records": records}, "baseline state"),
        evidence=_freeze_json(evidence, "baseline evidence"), history=tuple(history),
    )
