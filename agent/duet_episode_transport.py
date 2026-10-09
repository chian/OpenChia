"""Freeze a bound Duet's concrete route for its refinement Episodes.

This is not a Target Workflow launch configuration or an auxiliary model selection.
Credentials remain in this host object; only its nonsecret identity is durable.
"""

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from agent.duet_contracts import canonical_json
from agent.episode_launch_transport import invoke_pinned_route, provider_failure
from llm_call_library.transport import ModelCallFailed, ModelTransportResponse


@dataclass(frozen=True)
class DuetEpisodeBinding:
    owner_duet_id: str
    reference: dict
    record: dict
    api_key: str | None = field(repr=False)

    @classmethod
    def from_bound_agent(cls, *, artifacts, owner_duet_id, agent, model_types):
        from episode_runtime.records.experiments import put_data

        if agent is None:
            raise ValueError(
                "Bind the owning Duet agent before testing its refiner; Target Workflow launch settings cannot supply its model."
            )
        if (
            getattr(getattr(agent, "_duet_identity", None), "duet_id", None) is None
            or agent._duet_identity.duet_id.value != owner_duet_id
        ):
            raise ValueError(
                "The model agent is not bound to the campaign's owning Duet."
            )
        runtime = agent._current_main_runtime()
        required = ("model", "provider", "base_url", "api_mode", "session_id")
        if any(
            not isinstance(runtime.get(key), str) or not runtime[key].strip()
            for key in required
        ):
            raise ValueError(
                "The owning Duet must have a concrete model, provider, endpoint, API mode and session identity."
            )
        if runtime["api_mode"] not in {
            "chat_completions",
            "codex_responses",
            "anthropic_messages",
        }:
            raise ValueError(
                "The owning Duet's API mode has no pinned Episode adapter; no alternate provider is selected."
            )
        url = urlsplit(runtime["base_url"])
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "The Duet endpoint must be an explicit HTTP URL without embedded credentials or query parameters."
            )
        slots = sorted(set(model_types))
        if not slots or any(
            not isinstance(slot, str) or not slot.strip() for slot in slots
        ):
            raise ValueError("Refiner binding requires its exact declared model slots.")
        route = {
            key: runtime[key] for key in ("provider", "model", "base_url", "api_mode")
        }
        reasoning = getattr(agent, "reasoning_config", None)
        if reasoning is not None:
            route["reasoning"] = dict(reasoning)
        from agent.model_call_recovery_policy import resolve_recovery_policy

        route["recovery"] = resolve_recovery_policy(route)
        from agent.refiner_role_routes import configured_role_spec, resolve_role_routes

        spec, providers = configured_role_spec()
        role_routes = resolve_role_routes(spec, route, providers)
        record = {
            "schema_version": 1,
            "owner_duet_id": owner_duet_id,
            "session_id": runtime["session_id"],
            "source": "bound_duet_agent",
            "route": route,
            "model_types": slots,
            "auth_mode": runtime.get("auth_mode", ""),
            "credential_source": "owning_duet_host_memory",
        }
        if role_routes:
            # Pinned per-role overrides (agent/refiner_role_routes.py); no secrets.
            record["role_routes"] = role_routes
        reference = put_data(artifacts, owner_duet_id, "duet_model_binding", record)
        return cls(owner_duet_id, reference, record, runtime.get("api_key") or None)

    def validate(self, *, artifacts, reference, owner_duet_id, model_types):
        from episode_runtime.records.experiments import read_reference

        if owner_duet_id != self.owner_duet_id or reference != self.reference:
            raise ValueError(
                "Refiner execution requires the exact model binding of its owning Duet."
            )
        stored = read_reference(artifacts, reference, owner_duet_id)
        if stored["kind"] != "experiment.duet_model_binding.v1" or canonical_json(
            stored["record"]
        ) != canonical_json(self.record):
            raise ValueError(
                "The frozen Duet model binding differs from its host route."
            )
        if set(model_types) != set(self.record["model_types"]):
            raise ValueError(
                "The refiner's required model slots differ from the owning Duet binding."
            )

    def route_for(self, episode_local_id=None):
        """(role, route, key) for one call: a pinned role override or the Duet's route."""
        from agent.refiner_role_routes import route_key, select_route

        role, route = select_route(self.record.get("role_routes") or {}, self.record["route"], episode_local_id)
        return role, route, route_key(route, self.api_key)

    def for_role(self, *roles):
        """This binding with its route replaced by the first configured override of *roles*."""
        import dataclasses

        from agent.refiner_role_routes import route_key

        overrides = self.record.get("role_routes") or {}
        for role in roles:
            if role in overrides:
                route = overrides[role]
                return dataclasses.replace(
                    self, record={**self.record, "route": route, "refiner_role": role},
                    api_key=route_key(route, self.api_key),
                )
        return self

    def transport(self, *, record_attempt, cancel_event=None):
        return DuetEpisodeTransport(
            self, record_attempt=record_attempt, cancel_event=cancel_event
        )


class DuetEpisodeTransport:
    def __init__(self, binding, *, record_attempt, cancel_event=None):
        self.binding = binding
        self.record_attempt = record_attempt
        self.cancel = cancel_event or threading.Event()

    async def __call__(self, request):
        if request.model_type not in self.binding.record["model_types"]:
            raise ValueError("Model call names a slot outside the frozen Duet binding.")
        role, route, key = self.binding.route_for(request.episode_local_id)
        receipt = {
            "binding_ref": self.binding.reference,
            **({"refiner_role": role} if role else {}),
            "owner_duet_id": self.binding.owner_duet_id,
            "session_id": self.binding.record["session_id"],
            "call_id": uuid.uuid4().hex,
            "model_type": request.model_type,
            "episode_local_id": request.episode_local_id,
            "task": request.task,
            **{
                key: route[key] for key in ("provider", "model", "base_url", "api_mode")
            },
        }
        started = time.monotonic()
        self.record_attempt({**receipt, "state": "started"})
        try:
            text, actual_model = await invoke_pinned_route(
                route, key, request, self.cancel, lambda: None,
                record_activity=lambda details: self.record_attempt({**receipt, **details}),
            )
        except asyncio.CancelledError:
            self.record_attempt({
                **receipt,
                "state": "cancelled",
                "elapsed_seconds": time.monotonic() - started,
            })
            raise
        except Exception as exc:
            self.record_attempt({
                **receipt,
                "state": "failed",
                **provider_failure(exc, route, credential=key, request=request),
                "elapsed_seconds": time.monotonic() - started,
            })
            raise ModelCallFailed(
                "Owning Duet model request failed; no alternate route was selected.",
                receipt,
            ) from None
        self.record_attempt({
            **receipt,
            "state": "succeeded",
            "response_model": actual_model,
            "elapsed_seconds": time.monotonic() - started,
        })
        return ModelTransportResponse(
            text=text, route={**receipt, "response_model": actual_model}
        )


def required_slots(inputs):
    from episode_builder.planner import required_model_types

    return {
        slot
        for node in inputs.plan.nodes
        for slot in required_model_types(
            node.prompt_specs, node.selected_function_bindings
        )
    }
