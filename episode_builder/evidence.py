"""Preserve Builder model output before downstream validation can reject it.

These records are inert evidence, not admitted plans or runnable modules. They
retain exact prompts, raw response bytes, and the model boundary's diagnostic
even when no structured value survives. No generated source is executed here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json

from agent.duet_contracts import canonical_json, content_id
from agent.episode_contracts import OpaqueId, Sha256Digest
from llm_call_library.contracts import CallFailureKind, StructuredJSONResult
from llm_call_library.transport import ModelCallFailed

from ._contract_base import BuildAttempt
from .store import BuildStore, BuildStoreCorruptionError


ModelCallObserver = Callable[[Mapping[str, object]], None]


def observe_model_call(
    observer: ModelCallObserver | None,
    *,
    stage: str,
    local_id: str,
    system_prompt: str,
    prompt: str,
    prompt_record: Mapping[str, object],
    result: StructuredJSONResult,
    module_source: str | None = None,
) -> None:
    """Hand exact call evidence to its owner before handling the outcome."""

    record = {
        "stage": stage,
        "local_id": local_id,
        "system_prompt": system_prompt,
        "prompt": prompt,
        "prompt_record": prompt_record,
        "raw_response": result.raw_response,
        "module_source": module_source,
        "response_admitted": result.succeeded and result.value is not None,
        "trace": {
            "role": result.trace.role.value,
            "tier": result.trace.tier.value,
            "auxiliary_task": result.trace.auxiliary_task,
            "route": dict(result.trace.route),
        },
        "failure": (
            None
            if result.failure is None
            else {
                "kind": result.failure.kind.value,
                "message": result.failure.message,
            }
        ),
    }
    if observer is not None:
        observer(record)
    # Persist the unanswered request before stopping. Schema/answer rejection
    # is ordinary Builder evidence; unavailable model service is not.
    if result.failure is not None and result.failure.kind is CallFailureKind.MODEL_CALL:
        raise ModelCallFailed(
            "Builder model API request failed; execution stopped. Inspect /launch calls before explicitly continuing.",
            result.trace.route,
        )


class BuildCallEvidenceRecorder:
    """Bind an optional planner/emitter observer to one persisted attempt."""

    def __init__(self, *, store: BuildStore, build_attempt: BuildAttempt) -> None:
        stored = store.read_build_attempt(build_attempt.build_attempt_id)
        if stored.as_record() != build_attempt.as_record():
            raise ValueError("model evidence attempt differs from the persisted attempt")
        request = store.read_build_request(build_attempt.build_request_id)
        self.store = store
        self.build_attempt = build_attempt
        self.local_ids = frozenset(
            node.local_id for node in request.frozen_workflow.workflow.episodes
        )

    def __call__(self, call: Mapping[str, object]) -> None:
        if call["stage"] not in {"planning", "emission"}:
            raise ValueError("model evidence stage must be planning or emission")
        if call["local_id"] not in self.local_ids:
            raise ValueError("model evidence names an Episode outside the approved workflow")
        prompt_hash = self.store.put_blob(
            canonical_json(
                {
                    "system_prompt": call["system_prompt"],
                    "prompt": call["prompt"],
                    "prompt_record": call["prompt_record"],
                }
            ).encode("utf-8")
        )
        raw_hash = self.store.put_blob((call["raw_response"] or "").encode("utf-8"))
        source = call["module_source"]
        source_hash = (
            None if source is None else self.store.put_blob(source.encode("utf-8")).value
        )
        semantic_record = {
            "build_request_id": self.build_attempt.build_request_id.value,
            "build_attempt_id": self.build_attempt.build_attempt_id.value,
            "stage": call["stage"],
            "local_id": call["local_id"],
            "prompt_hash": prompt_hash.value,
            "raw_response_hash": raw_hash.value,
            "module_source_hash": source_hash,
            "response_admitted": call["response_admitted"],
            "trace": call["trace"],
            "failure": call["failure"],
        }
        evidence_id = content_id("build_model_call", semantic_record)
        self.store._put_record(
            f"model_calls/{self.build_attempt.build_attempt_id.value}",
            evidence_id,
            {
                "evidence_id": evidence_id.value,
                "content_hash": Sha256Digest.of_record(semantic_record).value,
                **semantic_record,
            },
        )

    @property
    def records(self) -> tuple[dict[str, object], ...]:
        return model_call_evidence_for_attempt(self.store, self.build_attempt)


def _admit_evidence_record(value: object) -> dict[str, object]:
    fields = {
        "evidence_id", "content_hash", "build_request_id", "build_attempt_id",
        "stage", "local_id", "prompt_hash", "raw_response_hash",
        "module_source_hash", "response_admitted", "trace", "failure",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("model-call evidence has an invalid shape")
    semantic = {
        key: item for key, item in value.items() if key not in {"evidence_id", "content_hash"}
    }
    if (
        content_id("build_model_call", semantic).value != value["evidence_id"]
        or Sha256Digest.of_record(semantic).value != value["content_hash"]
    ):
        raise ValueError("model-call evidence identity is stale")
    if value["stage"] not in {"planning", "emission"}:
        raise ValueError("model-call evidence has an invalid stage")
    if not isinstance(value["response_admitted"], bool):
        raise ValueError("model-call evidence response_admitted must be boolean")
    return dict(value)


def model_call_evidence_for_attempt(
    store: BuildStore,
    attempt: BuildAttempt | OpaqueId | str,
) -> tuple[dict[str, object], ...]:
    """Read verified call records and blobs without a live recorder instance."""

    build_attempt = store.read_build_attempt(
        attempt.build_attempt_id if isinstance(attempt, BuildAttempt) else attempt
    )
    if isinstance(attempt, BuildAttempt) and attempt.as_record() != build_attempt.as_record():
        raise ValueError("requested model evidence attempt differs from stored attempt")
    request = store.read_build_request(build_attempt.build_request_id)
    local_ids = {node.local_id for node in request.frozen_workflow.workflow.episodes}
    records: list[dict[str, object]] = []
    # Attempt-owned directories make unrelated corrupt calls irrelevant and
    # bound this read to the calls belonging to the requested attempt.
    category = f"model_calls/{build_attempt.build_attempt_id.value}"
    directory = store.builds_root / "records" / category
    for path in sorted(directory.glob("*.json")):
        record = store._read_record(category, path.stem, _admit_evidence_record)
        if record["evidence_id"] != path.stem:
            raise BuildStoreCorruptionError("model-call evidence filename differs from its identity")
        if (
            record["build_attempt_id"] != build_attempt.build_attempt_id.value
            or record["build_request_id"] != build_attempt.build_request_id.value
            or record["local_id"] not in local_ids
        ):
            raise BuildStoreCorruptionError("model-call evidence belongs to another workflow")
        prompt_bytes = store.read_blob(record["prompt_hash"])
        try:
            prompt = json.loads(prompt_bytes)
            if (
                not isinstance(prompt, Mapping)
                or set(prompt) != {"system_prompt", "prompt", "prompt_record"}
                or not isinstance(prompt["system_prompt"], str)
                or not isinstance(prompt["prompt"], str)
                or not isinstance(prompt["prompt_record"], Mapping)
                or canonical_json(prompt).encode("utf-8") != prompt_bytes
                or canonical_json(json.loads(prompt["prompt"]))
                != canonical_json(prompt["prompt_record"])
            ):
                raise ValueError("model-call prompt record differs from its exact prompt")
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise BuildStoreCorruptionError("model-call prompt blob is invalid") from exc
        store.read_blob(record["raw_response_hash"])
        if record["module_source_hash"] is not None:
            store.read_blob(record["module_source_hash"])
        records.append(record)
    return tuple(sorted(records, key=lambda row: (row["stage"], row["local_id"], row["evidence_id"])))


__all__ = [
    "BuildCallEvidenceRecorder",
    "ModelCallObserver",
    "model_call_evidence_for_attempt",
    "observe_model_call",
]
