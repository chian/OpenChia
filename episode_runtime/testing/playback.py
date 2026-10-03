"""Exact external-response reuse for the shared Run brokers.

Only the enclosing Run key is rebound, explicitly in provenance. Request
contents, nested keys and call order within an invocation are never rewritten.
In particular, a prompt containing an old/new Run ID is a different request.
"""

from collections import defaultdict, deque
import json

from agent.duet_contracts import canonical_json, digest_record

from ..broker import admit_model_request, admit_model_response, model_request_record
from ..http_contracts import admit_http_request, admit_http_response
from ..protocol import _episode_path, _thaw_json
from .recordings import HOST_EXCHANGE_CHANNELS, load_recording, read_recording
from ..records.experiments import read_record


_NORMALIZERS = {
    "model": lambda value: model_request_record(admit_model_request(_thaw_json(value))),
    "http": admit_http_request,
}


class ReplayDivergence(ValueError):
    def __init__(self, detail):
        self.detail = detail
        super().__init__("recorded response divergence: " + canonical_json(detail))


def execution_context(registration, *, environment_ref, launch_ref):
    from ..scoped import FreshEntryScope

    payload = registration.launch_request.as_record()
    payload.pop("request_id")  # correlation identity, not an experimental input
    return {
        "workflow_id": registration.workflow_id.value,
        "workflow_hash": registration.workflow_hash.value,
        "launch_inputs": payload,
        "environment_ref": environment_ref,
        "model_launch_ref": launch_ref,
        "egress_policy": registration.as_record()["egress_policy"],
        "max_frame_bytes": registration.runtime_policy.max_frame_bytes,
        **(
            {"component_scope": registration.execution_scope.as_record()}
            if registration.execution_scope is not None
            and registration.execution_scope.kind == "component"
            else {}
        ),
        **(
            {
                "fresh_entry": {
                    key: registration.execution_scope.as_record()["boundary"][key]
                    for key in (
                        "origin",
                        "workflow_hash",
                        "build_receipt_id",
                        "path_grains",
                        "path_local_ids",
                        "edge_slots",
                        "goals",
                        "input_payload",
                        "definition_ref",
                    )
                }
            }
            if isinstance(registration.execution_scope, FreshEntryScope)
            else {}
        ),
    }


def prepare_playback(artifacts, runs, reference, registration, context):
    source, recording = load_recording(
        artifacts, runs, reference, registration.duet_id.value
    )
    row = read_record(artifacts, "execution", run_id=source.run_id.value)
    if row is None:
        raise ValueError("recording lacks a verified shared execution binding")
    binding = row["record"]
    if binding["registration"] != source.as_record():
        raise ValueError("recording execution binding differs from its source Run")
    previous = binding.get("context")
    if (
        previous is None
        or previous["environment_ref"] is None
        or previous["model_launch_ref"] is None
    ):
        raise ValueError(
            "recording lacks frozen environment and model configuration context"
        )
    # Recorded mode needs no currently available model account. A supplied
    # launch_ref must still be exactly the recorded configuration, not a change.
    context = {
        **context,
        "model_launch_ref": context["model_launch_ref"] or previous["model_launch_ref"],
    }
    if canonical_json(previous) != canonical_json(context):
        raise ReplayDivergence({
            "kind": "execution_context_mismatch",
            "source_context_hash": digest_record(previous).value,
            "requested_context_hash": digest_record(context).value,
        })
    complete = read_recording(
        runs, source.run_id, through_event_ref=recording["through_event_ref"],
        projection_version=recording["schema_version"],
    )
    scope = registration.execution_scope
    from ..scoped import FreshEntryScope

    if scope is None:
        if (
            source.execution_scope is not None
            or recording["selected_episode_ids"] != complete["selected_episode_ids"]
        ):
            raise ValueError(
                "whole-workflow playback requires the complete recorded invocation set"
            )
    elif scope.kind == "component":
        if (
            source.execution_scope != scope
            or recording["selected_episode_ids"] != complete["selected_episode_ids"]
        ):
            raise ValueError(
                "component playback requires its exact bound call and complete recording"
            )
    elif isinstance(scope, FreshEntryScope):
        if not isinstance(source.execution_scope, FreshEntryScope):
            raise ValueError(
                "fresh checker entry replay requires a matching typed-entry recording"
            )
        prefix = source.execution_scope.entry_path(source.run_id.value)
        selected = {
            row["episode_id"]
            for row in complete["invocations"]
            if tuple((part["grain"], part["key"]) for part in row["episode_path"])[
                : len(prefix)
            ]
            == prefix
        }
        if not selected or not selected <= set(recording["selected_episode_ids"]):
            raise ValueError("recording omits the declared checker entry")
        recording = read_recording(
            runs,
            source.run_id,
            episode_ids=selected,
            through_event_ref=recording["through_event_ref"],
            projection_version=recording["schema_version"],
        )
    else:
        prefix = scope.source_path
        selected = {
            row["episode_id"]
            for row in complete["invocations"]
            if tuple((part["grain"], part["key"]) for part in row["episode_path"])[
                : len(prefix)
            ]
            == prefix
        }
        if not selected or not selected <= set(recording["selected_episode_ids"]):
            raise ValueError("recording omits required selected-subtree invocations")
        recording = read_recording(
            runs,
            source.run_id,
            episode_ids=selected,
            through_event_ref=recording["through_event_ref"],
            projection_version=recording["schema_version"],
        )
    if any(gap.get("channel") not in HOST_EXCHANGE_CHANNELS for gap in recording["gaps"]):
        raise ValueError(
            "recording has missing content or uncommitted responses; inspect its gaps"
        )
    return RecordingCursor(
        recording, source.run_id.value, registration.run_id.value
    ), context


class RecordingCursor:
    def __init__(self, recording, source_run_id, target_run_id):
        self.recording = json.loads(canonical_json(recording))
        self.source_run_id, self.target_run_id = source_run_id, target_run_id
        self._pending = defaultdict(deque)
        self._used = []
        self._divergence = None
        self._latest = {}
        for row in sorted(
            self.recording["exchanges"], key=lambda value: value["request_sequence"]
        ):
            if row["kind"] in HOST_EXCHANGE_CHANNELS:
                continue
            key = self._path(row["episode_path"], source_run_id)
            self._pending[key].append(row)

    @staticmethod
    def _path(raw, run_id):
        path = tuple((part["grain"], part["key"]) for part in _episode_path(raw))
        if path[0][1] != run_id:
            raise ValueError("recorded context must start at its exact Run-root key")
        return ((path[0][0], "<enclosing-run>"), *path[1:])

    @property
    def latest_provenance(self):
        return json.loads(canonical_json(self._latest))

    def take(self, kind, request, episode_path):
        if self._divergence is not None:
            raise ReplayDivergence(self._divergence)
        if kind not in _NORMALIZERS:
            self._divergence = {"kind": "unsupported_replay_channel", "channel": kind}
            raise ReplayDivergence(self._divergence)
        admitted = _NORMALIZERS[kind](request)
        try:
            key = self._path(episode_path, self.target_run_id)
        except ValueError as exc:
            self._divergence = {
                "kind": "invocation_context_mismatch",
                "target_run_id": self.target_run_id,
            }
            raise ReplayDivergence(self._divergence) from exc
        queue = self._pending.get(key)
        expected = queue[0] if queue else None
        if (
            expected is None
            or expected["kind"] != kind
            or canonical_json(_NORMALIZERS[kind](expected["request"]))
            != canonical_json(admitted)
        ):
            self._divergence = {
                "kind": "unmatched_external_request",
                "channel": kind,
                "episode_path": _thaw_json(episode_path),
                "request_hash": digest_record(admitted).value,
                "expected_request_hash": None
                if expected is None
                else expected["request_hash"],
                "expected_request_event_ref": None
                if expected is None
                else expected["request_event_ref"],
            }
            raise ReplayDivergence(self._divergence)
        response = expected["response"]
        if kind == "model":
            admit_model_response(response)
        else:
            response = admit_http_response(response)
        queue.popleft()
        self._latest = {
            "recording_id": self.recording["recording_id"],
            "request_event_ref": expected["request_event_ref"],
            "response_event_ref": expected["response_event_ref"],
            "run_key_binding": {
                "source": self.source_run_id,
                "target": self.target_run_id,
            },
        }
        self._used.append(self.latest_provenance)
        return json.loads(canonical_json(response))

    def report(self):
        unused = sum(len(queue) for queue in self._pending.values())
        return {
            "recording_id": self.recording["recording_id"],
            "source_registration_ref": self.recording["registration_ref"],
            "reused_responses": self._used,
            "unused_response_count": unused,
            "non_reused_exchange_counts": {
                kind: sum(row["kind"] == kind for row in self.recording["exchanges"])
                for kind in HOST_EXCHANGE_CHANNELS
            },
            "non_reused_exchange_gaps": [
                gap for gap in self.recording["gaps"]
                if gap.get("channel") in HOST_EXCHANGE_CHANNELS
            ],
            "divergence": self._divergence,
            "status": "diverged"
            if self._divergence
            else ("recording_suffix_unused" if unused else "matched"),
            "limitations": [
                "External responses were reused, not newly observed.",
                "Host learning, refinement and experiment operations are recomputed where supported, not answered by recorded host responses.",
                "This is a new execution, not restoration of nested checkpoint state.",
            ],
        }
