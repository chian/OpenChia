"""Builder continuation using its existing prompt/response evidence.

The Builder remains one-shot. A continuation gets a linked physical attempt;
completed calls are recovered by exact prompt identity, never by LLM summaries.
"""

import json
import os
from dataclasses import replace

from agent.duet_contracts import DuetProvenance, canonical_json, content_id
from agent.episode_contracts import OpaqueId
from episode_builder.evidence import model_call_evidence_for_attempt
from episode_builder.service import _materializer_identity
from episode_runtime.records.experiments import artifact_fields, read_record
from llm_call_library.transport import ModelTransportResponse


def owner_record():
    from openchia_cli.active_sessions import _own_start_time

    started = _own_start_time()
    if started is None:
        raise ValueError("Build ownership requires a verifiable process identity.")
    return {"pid": os.getpid(), "process_start_time": started}


def requested_jobs(host):
    state = host.store.get_duet(host.identity.duet_id.value)
    return [
        event["record"] for event in host.store.events(host.identity.duet_id.value)
        if event["event_type"] == "build_requested"
        and event["record"]["authority_head_approval_id"] == state["authority_head_approval_id"]
    ]


def builder_owner_status(host, job):
    from openchia_cli.active_sessions import _pid_liveness

    finished = [
        event
        for event in host.store.events(host.identity.duet_id.value)
        if event["event_type"] in {"build_finished", "build_host_failure"}
        and event["record"]["build_request_id"] == job["build_request_id"]
    ]
    if finished:
        final = finished[-1]
        return {
            "state": "finished",
            "build_state": final["record"].get("state", "host_error"),
            "event_sequence": final["sequence"],
        }
    owner = job.get("owner")
    live = None if owner is None else _pid_liveness(owner["pid"], owner["process_start_time"])
    return {"state": {True: "live", False: "stopped", None: "unknown"}[live]}


def require_owner_stopped(host, job):
    if builder_owner_status(host, job)["state"] not in {"finished", "stopped"}:
        raise ValueError("Previous Builder owner is live or unverifiable; it cannot be restarted.")


def unfinished_builder_status(host, current):
    """Expose an interrupted Builder even when it never published a baseline."""
    jobs = requested_jobs(host)
    if not jobs or jobs[-1]["build_request_id"] == current.get("build_request_id"):
        return current
    job = jobs[-1]
    request_id = job["build_request_id"]
    if read_record(host.store, "build_job", build_request_id=request_id) is not None:
        return current
    attempts = host.build_store.attempts_for_build_request(request_id)
    receipts = host.build_store.receipts_for_build_request(request_id)
    progress = [
        {key: value for key, value in event["record"].items() if key != "build_request_id"}
        for event in host.store.events(host.identity.duet_id.value)
        if event["event_type"] == "build_progress"
        and event["record"]["build_request_id"] == request_id
    ]
    ownership = builder_owner_status(host, job)
    state = ownership.get("build_state") or {
        "stopped": "interrupted", "live": "building", "unknown": "ownership_unknown",
    }[ownership["state"]]
    return {
        **current, "state": state, "build_request_id": request_id,
        "build_attempt_id": None if not attempts else attempts[0].build_attempt_id.value,
        "build_receipt_id": None if not receipts else receipts[0].receipt_id.value,
        "materialized_specification_id": None, "refinement_baseline_id": None,
        "progress": host._empty_progress(state) if not progress else progress[-1],
        "refinement": None, "error": None,
        "ownership": ownership,
        "continuation": {
            "command": "/build continue", "stage": "builder", "owner_verification_required": True,
            "owner_check_passed": ownership["state"] in {"finished", "stopped"},
        },
    }


def continued_materialization_request(host, request, builder):
    """Find/restart the shipped deterministic materializer using normal attempts.

    No model response is fabricated or source identity loosened. Its inert
    adapters are reproducible; a consumed partial nonce gets a linked successor,
    while a completed receipt is returned without another Builder invocation.
    """
    # Fresh authorization has no stored request yet. The claim lookup below
    # requires it, before EpisodeBuilder.build would normally publish it.
    host.build_store.put_build_request(request)
    identity = _materializer_identity(builder.planner.call_options, builder.emitter.call_options)
    seen = set()
    while request.build_request_id.value not in seen:
        seen.add(request.build_request_id.value)
        link = read_record(host.store, "build_continuation", predecessor_build_request_id=request.build_request_id.value)
        if link is not None:
            successor = host.build_store.read_build_request(link["record"]["build_request_id"])
            if replace(successor, request_nonce=request.request_nonce) != request:
                raise ValueError("materializer continuation changes its approved request")
            request = successor
            continue
        receipts = host.build_store.receipts_for_build_request(request.build_request_id)
        if receipts:
            if len(receipts) != 1:
                raise ValueError("materializer has ambiguous completed receipts")
            if not any(item.code == "build_cancelled" for item in receipts[0].deficits):
                return request, receipts[0]
        attempts = host.build_store.attempts_for_build_request(request.build_request_id)
        if not attempts and not host.build_store.build_request_consumed(request.build_request_id):
            return request, None
        if any(attempt.materializer != identity for attempt in attempts):
            raise ValueError("materializer source changed; the partial attempt cannot be continued")
        successor = replace(request, request_nonce=content_id(
            "build_continue", {"predecessor": request.build_request_id.value}
        ).value)
        host.build_store.put_build_request(successor)
        link = {"predecessor_build_request_id": request.build_request_id.value,
                "build_request_id": successor.build_request_id.value}
        fields = (
            artifact_fields("build_continuation", duet_id=request.frozen_workflow.duet_id.value,
                            predecessor_build_request_id=request.build_request_id.value, record=link),
            artifact_fields("build_parent", duet_id=request.frozen_workflow.duet_id.value,
                            build_request_id=successor.build_request_id.value, record=link),
        )
        with host.store.transaction():
            for item in fields:
                host.store.put_artifact(**item)
        request = successor
    raise ValueError("materializer continuation lineage contains a cycle")


class BuilderResponses:
    """One exact-history adapter on the existing model transport, not a runner."""

    def __init__(self, host, builder, predecessor, live, successor):
        self.host, self.live, self.successor = host, live, successor
        self.progress = lambda: None
        self.pending = {}
        self.error = None
        identity = _materializer_identity(builder.planner.call_options, builder.emitter.call_options)
        seen = set()
        request = predecessor
        while request.build_request_id.value not in seen:
            seen.add(request.build_request_id.value)
            if replace(request, request_nonce=predecessor.request_nonce) != predecessor:
                raise ValueError("Builder continuation lineage changes the approved request.")
            for attempt in host.build_store.attempts_for_build_request(request.build_request_id):
                if attempt.materializer != identity:
                    raise ValueError("Builder source/model configuration changed; continuation cannot reuse its old execution.")
                for evidence in model_call_evidence_for_attempt(host.build_store, attempt):
                    # A failed transport produced no response to preserve. Its
                    # unanswered request may be submitted after the saved prefix.
                    failure = evidence["failure"]
                    if failure is not None and failure["kind"] == "model-call":
                        continue
                    key = ("builder." + evidence["stage"], evidence["local_id"])
                    old = self.pending.get(key)
                    if old is not None and any(
                        old[field] != evidence[field]
                        for field in ("prompt_hash", "raw_response_hash", "failure", "response_admitted")
                    ):
                        raise ValueError("Builder history has conflicting responses for one stage and Episode.")
                    self.pending[key] = evidence
            parent = read_record(host.store, "build_parent", build_request_id=request.build_request_id.value)
            if parent is None:
                break
            if (parent["duet_id"] != host.identity.duet_id.value
                    or parent["record"]["build_request_id"] != request.build_request_id.value):
                raise ValueError("Builder continuation belongs to another Duet.")
            request = host.build_store.read_build_request(OpaqueId(parent["record"]["predecessor_build_request_id"]))
        else:
            raise ValueError("Builder continuation lineage contains a cycle.")

    def fail(self, message):
        self.error = message
        raise ValueError(message)

    async def __call__(self, request):
        if self.error is not None:
            raise ValueError(self.error)
        key = (request.call_role, request.episode_local_id)
        evidence = self.pending.get(key)
        if evidence is None:
            if self.pending:
                self.fail("Builder diverged before consuming its committed response history.")
            self.live.progress = self.progress
            return await self.live(request)
        prompt = json.loads(self.host.build_store.read_blob(evidence["prompt_hash"]))
        expected = [
            {"role": "system", "content": prompt["system_prompt"]},
            {"role": "user", "content": prompt["prompt"]},
        ]
        if canonical_json(request.messages) != canonical_json(expected):
            self.fail("Builder continuation prompt differs from its committed evidence.")
        self.pending.pop(key)
        self.host.store.append_event(
            duet_id=self.host.identity.duet_id.value, event_type="build_model_response_reused",
            provenance=DuetProvenance.HOST_VALIDATION.value,
            record={
                "build_request_id": self.successor.build_request_id.value,
                "source_build_attempt_id": evidence["build_attempt_id"],
                "source_evidence_id": evidence["evidence_id"],
                "source_evidence_hash": evidence["content_hash"],
            },
        )
        return ModelTransportResponse(
            text=self.host.build_store.read_blob(evidence["raw_response_hash"]).decode("utf-8"),
            route=evidence["trace"]["route"],
        )

    def validate_complete(self):
        if self.error is not None or self.pending:
            raise ValueError(self.error or "Builder did not consume its complete saved response history.")
