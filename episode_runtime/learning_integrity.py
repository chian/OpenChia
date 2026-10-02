"""Transaction assertions at the durable RunStore publication boundary."""

from collections.abc import Mapping
import hashlib

from function_library.epistemic_contract import exact
from function_library.epistemic_schemas import canonical, identity

from .contracts import RunEventKind, RunEventOrigin


def validate_learning_commit(*, events, origin, episode_id, payload):
    if origin is not RunEventOrigin.HOST_LEARNING or episode_id is None:
        raise ValueError("only the host learning boundary may commit operative state")
    exact(
        payload,
        {
            "request_hash",
            "unit_id",
            "state",
            "baseline_ids",
            "observation_ids",
            "receipt",
        },
        "learning commit",
    )
    receipt = payload["receipt"]
    if not isinstance(receipt, Mapping):
        raise ValueError("learning commit requires a typed receipt")
    if receipt["unit_id"] != payload["unit_id"]:
        raise ValueError("learning receipt names another unit")
    if (
        identity("receipt", {k: v for k, v in receipt.items() if k != "receipt_id"})
        != receipt["receipt_id"]
    ):
        raise ValueError("learning receipt hash is stale")
    prior_commits = [
        e
        for e in events
        if e.kind is RunEventKind.LEARNING_COMMITTED and e.episode_id == episode_id
    ]
    if receipt["ordinal"] != len(prior_commits):
        raise ValueError("learning commits cannot repeat or skip a unit")
    audits = [
        e
        for e in events
        if e.kind is RunEventKind.LEARNING_ATTEMPT
        and e.episode_id == episode_id
        and e.event_id.value == receipt["audit_ref"]
    ]
    if len(audits) != 1 or audits[0].payload["request_hash"] != payload["request_hash"]:
        raise ValueError("learning requires the exact prior committed attempt audit")
    refs = {
        e.payload["artifact"]["artifact_id"]
        for e in events
        if e.kind is RunEventKind.LEARNING_EVIDENCE
        and e.origin is RunEventOrigin.HOST_LEARNING
    }
    delta = receipt["admission"]["transitions"]
    prior_state = next(
        (
            e.payload["state"]
            for e in reversed(events)
            if e.kind is RunEventKind.LEARNING_COMMITTED
        ),
        {"records": []},
    )
    replay = {r["record_id"]: r for r in prior_state["records"]}
    touched = set()
    for transition in delta:
        if (
            transition["audit_ref"] != receipt["audit_ref"]
            or not transition["evidence_refs"]
            or not set(transition["evidence_refs"]).issubset(refs)
        ):
            raise ValueError("learning transition has no committed evidence lineage")
        if transition["before"] == transition["after"]:
            raise ValueError("learning transition does not change state")
        after = transition["after"]
        key = after["record_id"]
        if key in touched or canonical(transition["before"]) != canonical(
            replay.get(key)
        ):
            raise ValueError(
                "learning transition does not match its durable predecessor"
            )
        if transition["transition_id"] != identity(
            "transition", {k: v for k, v in transition.items() if k != "transition_id"}
        ):
            raise ValueError("learning transition hash is stale")
        digest = (
            "sha256:"
            + hashlib.sha256(
                canonical({k: v for k, v in after.items() if k != "content_hash"})
            ).hexdigest()
        )
        if digest != after["content_hash"]:
            raise ValueError("learning record hash is stale")
        replay[key] = after
        touched.add(key)
        if not any(
            canonical(record) == canonical(transition["after"])
            for record in payload["state"]["records"]
        ):
            raise ValueError(
                "learning transition is absent from the durable checkpoint"
            )
    checkpoint = payload["state"]["records"]
    if len(checkpoint) != len(replay) or any(
        canonical(r) != canonical(replay.get(r["record_id"])) for r in checkpoint
    ):
        raise ValueError("learning checkpoint contains unadmitted changes")
    measurement = receipt["measurement"]
    realized = measurement["realized_yield"]
    if type(realized) is not int or realized < 0 or (realized > 0 and not delta):
        raise ValueError("positive yield requires a committed admitted-state delta")
    if realized != len(set(measurement["identity_ids"])) or not set(
        measurement["identity_ids"]
    ).issubset(
        t["after"]["record_id"]
        for t in delta
        if t["before"] is None and t["after"]["status"] == "active"
    ):
        raise ValueError(
            "yield identities must come from newly admitted operative records"
        )
    known = {r.get("equivalence_key", r["record_id"]) for r in prior_state["records"]}
    if any(
        replay[key].get("equivalence_key", key) in known
        for key in measurement["identity_ids"]
    ):
        raise ValueError("equivalent knowledge cannot earn credit twice")
    before = sum(
        e.payload["receipt"]["measurement"]["realized_yield"] for e in prior_commits
    )
    if (
        measurement["credit_before"] != before
        or measurement["credit_after"] != before + realized
    ):
        raise ValueError("learning credit update does not match durable history")
