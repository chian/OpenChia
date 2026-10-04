"""Host exchanges and their committed recording, shared by every Run caller.

Only worker-visible request/response records enter the audit. Host credentials
are added inside the broker, never copied into this recording.
"""

import asyncio
from urllib.parse import urlsplit

from agent.duet_contracts import digest_record
from agent.episode_contracts import OpaqueId
from function_library.epistemic_schemas import model_call_id

from .broker import (
    admit_model_request,
    model_request_hash,
    model_response_hash,
    model_response_record,
)
from .contracts import RunEventKind, RunEventOrigin
from .http_broker import http_response_bytes
from .http_contracts import http_request_hash, http_response_hash
from .protocol import HostFrameType, _thaw_json
from .host_tasks import commit_local, join_local


async def broker_refinement_request(
    *, run_store, registration, channel, frame, session
):
    """Record host communication without replacing campaign admission evidence."""
    await _broker_operation(
        kind="refinement", run_store=run_store, registration=registration,
        channel=channel, frame=frame, session=session,
    )


async def broker_experiment_request(
    *, run_store, registration, channel, frame, session
):
    """Preserve experiment intent and response on the testing Run's own audit."""
    await _broker_operation(
        kind="experiment", run_store=run_store, registration=registration,
        channel=channel, frame=frame, session=session,
    )


async def broker_learning_request(
    *, run_store, registration, channel, frame, session
):
    """Record the exact learning response separately from its admitted delta."""
    await _broker_operation(
        kind="learning", run_store=run_store, registration=registration,
        channel=channel, frame=frame, session=session,
    )


async def _broker_operation(
    *, kind, run_store, registration, channel, frame, session
):
    task = asyncio.create_task(_complete_operation(
        kind=kind, run_store=run_store, registration=registration,
        channel=channel, frame=frame, session=session,
    ))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Propagate cancellation to network/nested execution, but join any
        # synchronous host transaction before terminal publication is allowed.
        task.cancel()
        try:
            await join_local(task, propagate_cancel=False)
        except asyncio.CancelledError:
            pass
        except Exception as error:
            # A disconnect after the local receipt committed must not turn a
            # requested cancellation into an uncontinuable failed execution.
            raise asyncio.CancelledError from error
        raise


async def _complete_operation(
    *, kind, run_store, registration, channel, frame, session
):
    from .protocol import ProtocolError

    if session is None:
        raise ProtocolError(f"this Run has no admitted {kind} session")
    body = _thaw_json(frame.body)
    episode_id = OpaqueId(body["episode_id"])
    request = {"operation": body["operation"], "payload": body["payload"]}
    request_hash = digest_record(request).value
    prior_state = (
        await asyncio.to_thread(session.continuation_state)
        if kind == "refinement" and not session.initial_state_recorded else None
    )
    request_event = await commit_local(
        run_store.append_event,
        run_id=registration.run_id,
        origin=RunEventOrigin.WORKER,
        sender_sequence=frame.sender_sequence,
        kind=RunEventKind(kind + "_requested"),
        episode_id=episode_id,
        payload={
            **body, "request": request, "request_hash": request_hash,
            **({"session_state_before": prior_state} if prior_state is not None else {}),
        },
    )
    if kind == "refinement":
        session.initial_state_recorded = True
    if kind == "learning":
        response = await session(episode_id.value, body["operation"], body["payload"])
    else:
        response = await session.exchange(
            episode_id=episode_id,
            episode_path=body["episode_path"],
            operation=body["operation"],
            payload=body["payload"],
            **({"request_event": request_event} if kind == "refinement" else {}),
        )
    # The refiner holds admitted parent/child bindings in host memory. Retain
    # that state with the reply, separately from worker-visible result data.
    # Learning state and experiment ownership already live in their stores.
    session_state = (
        await asyncio.to_thread(session.continuation_state)
        if kind == "refinement" else None
    )
    response_body = {"request_id": body["request_id"], "response": response}
    prepared = channel.prepare(HostFrameType(kind + "_response").value, response_body)
    # Frame validation and sequence reservation precede persistence; publication
    # follows it. Neither an oversized reply nor cancellation may orphan the Run.
    await commit_local(
        run_store.append_event,
        run_id=registration.run_id,
        origin=RunEventOrigin.HOST,
        sender_sequence=prepared[0].sender_sequence,
        kind=RunEventKind(kind + "_responded"),
        episode_id=episode_id,
        payload={
            **response_body, "request_hash": request_hash,
            "response_hash": digest_record(response).value,
            **({"session_state": session_state} if session_state is not None else {}),
        },
    )
    await channel.publish(prepared)


async def broker_model_request(
    *, run_store, registration, channel, frame, model_broker
):
    # Protocol frames freeze lists for hashing; broker inputs are plain JSON.
    request_record = _thaw_json(frame.body["request"])
    request = admit_model_request(request_record)
    request_hash = model_request_hash(request)
    episode_id = OpaqueId(frame.body["episode_id"])
    await commit_local(
        run_store.append_event,
        run_id=registration.run_id,
        origin=RunEventOrigin.WORKER,
        sender_sequence=frame.sender_sequence,
        kind=RunEventKind.MODEL_REQUESTED,
        episode_id=episode_id,
        payload={
            "model_request_id": frame.body["model_request_id"],
            "request_hash": request_hash.value,
            "task": request.task,
            "request": request_record,
            "episode_path": frame.body["episode_path"],
        },
    )
    response = await model_broker(
        request_record, episode_path=frame.body["episode_path"]
    )
    prepared = channel.prepare(
        HostFrameType.MODEL_RESPONSE.value,
        {
            "model_request_id": frame.body["model_request_id"],
            "response": model_response_record(response),
        },
    )
    await commit_local(
        run_store.append_event,
        run_id=registration.run_id,
        origin=RunEventOrigin.HOST,
        sender_sequence=prepared[0].sender_sequence,
        kind=RunEventKind.MODEL_RESPONDED,
        episode_id=episode_id,
        payload={
            "model_request_id": frame.body["model_request_id"],
            "request_hash": request_hash.value,
            "response_hash": model_response_hash(response).value,
            "producer_call_id": model_call_id(
                response.text, request.task, response.route
            ),
            "response_text": response.text,
            "route": dict(response.route),
            **model_broker.response_provenance(),
        },
    )
    await channel.publish(prepared)


async def broker_http_request(*, run_store, registration, channel, frame, http_broker):
    body = frame.body
    local_id = body["episode_path"][-1]["grain"]
    request = body["request"]
    request_hash = http_request_hash(request)
    episode_id = OpaqueId(body["episode_id"])
    matched = http_broker.match_rule(local_id, request)
    rule_name = None if matched is None else matched.name
    url = urlsplit(str(request["url"]))
    await commit_local(
        run_store.append_event,
        run_id=registration.run_id,
        origin=RunEventOrigin.WORKER,
        sender_sequence=frame.sender_sequence,
        kind=RunEventKind.HTTP_REQUESTED,
        episode_id=episode_id,
        payload={
            "http_request_id": body["http_request_id"],
            "request_hash": request_hash.value,
            "rule": rule_name,
            "method": request["method"],
            "host": url.hostname,
            "path": url.path,
            "request": request,
            "episode_path": body["episode_path"],
        },
    )
    response = await http_broker(
        local_id=local_id, request=request, episode_path=body["episode_path"]
    )
    prepared = channel.prepare(
        HostFrameType.HTTP_RESPONSE.value,
        {"http_request_id": body["http_request_id"], "response": response},
    )
    await commit_local(
        run_store.append_event,
        run_id=registration.run_id,
        origin=RunEventOrigin.HOST,
        sender_sequence=prepared[0].sender_sequence,
        kind=RunEventKind.HTTP_RESPONDED,
        episode_id=episode_id,
        payload={
            "http_request_id": body["http_request_id"],
            "request_hash": request_hash.value,
            "response_hash": http_response_hash(response).value,
            "outcome": response["outcome"],
            "status": response["status"],
            "response_bytes": http_response_bytes(response),
            "rule": response["rule"],
            "response": response,
            **http_broker.response_provenance(),
        },
    )
    await channel.publish(prepared)
