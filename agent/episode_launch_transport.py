"""Pinned model transport: explicit credentials, wire adapter and fallback order.

Uses the existing wire adapters and cancellation mechanism, not the auxiliary
provider-discovery ladder. A launch cannot hop to another logged-in account.
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from typing import Callable, Mapping

from agent.episode_launch import ResolvedLaunch
from llm_call_library.transport import ModelTransportRequest, ModelTransportResponse


class LaunchModelError(RuntimeError):
    def __init__(self, message: str, route: Mapping[str, str]) -> None:
        super().__init__(message)
        self.route = dict(route)


def _invoke(route: dict, key: str | None, request: ModelTransportRequest,
            cancel: threading.Event, progress: Callable[[], None]):
    import httpx
    from openai import OpenAI, Omit
    from agent.auxiliary_client import (
        AnthropicAuxiliaryClient, CodexAuxiliaryClient,
        _apply_required_codex_headers, _run_protected_sync_provider_call,
        aux_interrupt_protection, aux_progress_hook,
        extract_content_or_reasoning, scoped_runtime_main,
    )

    def strip_auth(outgoing: httpx.Request) -> None:
        if key is None:
            outgoing.headers.pop("authorization", None)
            outgoing.headers.pop("x-api-key", None)

    # Explicit transport ownership also prevents ambient proxies from changing
    # the destination. Each call owns its client, so cancellation cannot close
    # another project's connection.
    http = httpx.Client(trust_env=False, timeout=None, follow_redirects=False,
                        event_hooks={"request": [strip_auth]})
    mode = route["api_mode"]
    if mode == "anthropic_messages":
        from anthropic import Anthropic, Omit as AnthropicOmit
        from agent.anthropic_credentials import anthropic_route_is_oauth
        from agent.anthropic_adapter import (
            _beta_header, _common_betas_for_base_url, _get_claude_code_version,
            _OAUTH_ONLY_BETAS,
        )
        is_oauth = anthropic_route_is_oauth(route["base_url"], key, provider=route["provider"])
        headers = _beta_header(_common_betas_for_base_url(route["base_url"]) + (_OAUTH_ONLY_BETAS if is_oauth else []))
        headers["X-Api-Key" if is_oauth else "Authorization"] = AnthropicOmit()
        if is_oauth:
            headers.update({"user-agent": f"claude-code/{_get_claude_code_version()} (external, cli)", "x-app": "cli"})
        real = Anthropic(api_key="" if is_oauth else key or "no-auth",
                         auth_token=key if is_oauth else "", default_headers=headers, base_url=route["base_url"],
                         http_client=http, max_retries=0, timeout=None)
        client = AnthropicAuxiliaryClient(real, route["model"], key or "", route["base_url"], is_oauth=is_oauth)
    else:
        # Empty constructor values prevent SDK environment lookup; Omit keeps
        # those values off the wire (None alone would inherit another project).
        extras = {"http_client": http, "max_retries": 0, "timeout": None,
                  "organization": "", "project": "",
                  "default_headers": {"OpenAI-Organization": Omit(), "OpenAI-Project": Omit()}}
        if mode == "codex_responses":
            _apply_required_codex_headers(extras, access_token=key or "", base_url=route["base_url"])
        real = OpenAI(api_key=key or "no-auth", base_url=route["base_url"], **extras)
        client = CodexAuxiliaryClient(real, route["model"]) if mode == "codex_responses" else real
    kwargs = {"model": route["model"], "messages": [dict(x) for x in request.messages], "timeout": request.timeout}
    reasoning = route.get("reasoning", request.reasoning_config)
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if request.max_tokens is not None:
        from agent.auxiliary_client import auxiliary_max_tokens_param
        kwargs.update(auxiliary_max_tokens_param(request.max_tokens, model=route["model"]))
    if reasoning is not None:
        if mode == "codex_responses":
            kwargs["extra_body"] = {"reasoning": reasoning}
        elif mode == "anthropic_messages":
            kwargs["_reasoning_config"] = reasoning
        else:
            kwargs["reasoning_effort"] = reasoning["effort"] if reasoning["enabled"] else "none"
    try:
        with (aux_interrupt_protection(cancel_event=cancel), aux_progress_hook(progress),
              scoped_runtime_main({"provider": route["provider"], "model": route["model"],
                                   "base_url": route["base_url"], "api_mode": mode})):
            def create(payload):
                if mode == "codex_responses":
                    return _codex_response(client, real, payload, progress)
                return client.chat.completions.create(**payload)

            response = _run_protected_sync_provider_call(create, kwargs)
            from agent.aux_accounting import record_aux_usage
            record_aux_usage(response, request.task, provider=route["provider"], base_url=route["base_url"])
            return extract_content_or_reasoning(response) or "", str(getattr(response, "model", "") or route["model"])
    finally:
        real.close()


def _codex_response(client, real, kwargs, progress):
    """Reuse Responses conversion/assembly with this launch's cancellation policy.

    The auxiliary adapter's create() also installs task-default watchdogs. A
    pinned launch owns its timeout, so use its converter and stream consumer
    directly instead of inheriting that separate policy.
    """
    from types import SimpleNamespace
    from agent.auxiliary_client import _parse_codex_final_response
    from agent.codex_runtime import _consume_codex_event_stream

    # The converter includes timeout in payload, including an explicit None.
    # Its third return value is for the auxiliary watchdog we intentionally omit.
    payload, model, _ = client.chat.completions._build_responses_kwargs(kwargs)
    payload.pop("_wire_aliases", None)
    stream = real.responses.create(**payload, stream=True)
    try:
        final = stream if hasattr(stream, "output") else _consume_codex_event_stream(
            stream, model=payload["model"], on_event=lambda event: progress())
    finally:
        close = getattr(stream, "close", None)
        if close is not None:
            close()
    if final is None:
        raise RuntimeError("Responses stream ended without a final response")
    if getattr(final, "status", "completed") != "completed":
        raise RuntimeError("Responses stream did not complete successfully")
    text, _, usage = _parse_codex_final_response(final)
    return SimpleNamespace(model=getattr(final, "model", None) or payload["model"], usage=usage,
                           choices=[SimpleNamespace(message=SimpleNamespace(content="".join(text)))])


class LaunchModelTransport:
    def __init__(self, launch: ResolvedLaunch, *, launch_id: str,
                 record_attempt: Callable[[dict], None], cancel_event: threading.Event | None = None,
                 progress: Callable[[], None] = lambda: None) -> None:
        self.launch = launch
        self.launch_id = launch_id
        self.record_attempt = record_attempt
        self.cancel = cancel_event or threading.Event()
        self.progress = progress
        self._record = launch.record

    async def __call__(self, request: ModelTransportRequest) -> ModelTransportResponse:
        from agent.auxiliary_client import AuxiliaryExplicitCancellation

        record = self._record
        spec = record["resolved_spec"]
        role = request.call_role or "run"
        model_type = self.launch.model_type_for(request.model_type, role)
        names = self.launch.route_names(model_type, role)
        call_id = uuid.uuid4().hex
        last_receipt = {}
        for index, name in enumerate(names):
            if self.cancel.is_set():
                raise asyncio.CancelledError
            route = spec["routes"][name]
            receipt = {
                "launch_id": self.launch_id, "configuration_hash": self.launch.configuration_hash,
                "project": spec["project"], "call_id": call_id, "attempt": str(index + 1),
                "route_name": name, "provider": route["provider"], "model": route["model"],
                "model_type": model_type,
                "base_url": route["base_url"], "api_mode": route["api_mode"],
                "account": route["auth"].get("account", "no_auth"),
                "credential_source": record["sources"][f"routes.{name}.auth"],
                "episode_local_id": request.episode_local_id or "", "role": role, "task": request.task,
            }
            last_receipt = receipt
            controls = {"temperature": request.temperature, "max_tokens": request.max_tokens,
                        "timeout": request.timeout, "reasoning": route.get("reasoning", request.reasoning_config)}
            started = time.monotonic()
            self.record_attempt({**receipt, "state": "started", "controls": controls})
            try:
                text, actual_model = await asyncio.to_thread(
                    _invoke, route, self.launch.credentials[name], request, self.cancel, self.progress)
            except (AuxiliaryExplicitCancellation, asyncio.CancelledError):
                self.cancel.set()
                self.record_attempt({**receipt, "state": "cancelled", "elapsed_seconds": time.monotonic() - started})
                raise asyncio.CancelledError from None
            except Exception as exc:
                # Provider exceptions can echo credentials or response bodies.
                # Persist typed diagnostics, never their unfiltered text.
                self.record_attempt({**receipt, "state": "failed", "error_type": type(exc).__name__,
                                     "http_status": getattr(exc, "status_code", None),
                                     "elapsed_seconds": time.monotonic() - started})
                continue
            self.record_attempt({**receipt, "state": "succeeded", "response_model": actual_model,
                                 "elapsed_seconds": time.monotonic() - started})
            return ModelTransportResponse(text=text, route={**receipt, "response_model": actual_model})
        raise LaunchModelError("Declared model routes failed; inspect /launch calls for typed diagnostics.", last_receipt)
