"""Host effect receipts in the shared record store, linked to the Run journal.

A receipt is not a second replay log: it closes the transaction between a host
state change and its reply. The original request and all delivered replies stay
in the Run audit. A terminal Run is never edited to insert a missing response.
"""

from agent.duet_contracts import digest_record

from .experiments import put_record, read_record


def commit_receipt(artifacts, registration, event, response, session_state):
    from episode_runtime.testing_harness.recordings import event_reference

    record = {
        "request_event_ref": event_reference(event),
        "request_hash": event.payload["request_hash"],
        "response": response,
        "response_hash": digest_record(response).value,
        "session_state": session_state,
    }
    put_record(
        artifacts, "host_operation", duet_id=registration.duet_id.value,
        run_id=registration.run_id.value, request_id=event.payload["request_id"],
        record=record,
    )
    return record


def read_receipt(artifacts, registration, event):
    from episode_runtime.testing_harness.recordings import event_reference

    row = read_record(
        artifacts, "host_operation", run_id=registration.run_id.value,
        request_id=event.payload["request_id"],
    )
    if row is None:
        return None
    record = row["record"]
    if (
        row["duet_id"] != registration.duet_id.value
        or record["request_event_ref"] != event_reference(event)
        or record["request_hash"] != event.payload["request_hash"]
        or record["response_hash"] != digest_record(record["response"]).value
    ):
        raise ValueError("host operation receipt differs from its committed request")
    return {**record, "receipt_ref": {
        "artifact_id": row["artifact_id"], "content_hash": row["content_hash"],
    }}
