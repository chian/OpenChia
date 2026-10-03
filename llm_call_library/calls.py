"""Reusable model-call mechanics with no Episode-specific prompt content."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, TypeVar

from .contracts import (
    CallFailure,
    CallFailureKind,
    CallOptions,
    CallTrace,
    ModelRole,
    ModelTier,
    ProbabilityJudgmentRequest,
    ProbabilityJudgmentResult,
    ProbabilityVectorJudgmentRequest,
    ProbabilityVectorJudgmentResult,
    StructuredJSONRequest,
    StructuredJSONResult,
)
from .transport import ModelTransportRequest, call_model_transport


T = TypeVar("T")


_AUXILIARY_TASKS = {
    (ModelRole.STRUCTURED_JSON, ModelTier.REASONING): (
        "episode_structured_json_reasoning"
    ),
    (ModelRole.STRUCTURED_JSON, ModelTier.FAST): "episode_structured_json_fast",
    (ModelRole.PROBABILITY, ModelTier.REASONING): (
        "episode_probability_reasoning"
    ),
    (ModelRole.PROBABILITY, ModelTier.FAST): "episode_probability_fast",
}


@dataclass(frozen=True)
class _AttemptOutcome:
    value: Any = None
    failure: CallFailure | None = None
    raw_response: str = ""
    auxiliary_task: str = ""
    route: tuple[tuple[str, str], ...] = ()


def _parse_json(text: str) -> object:
    """Parse one JSON value, tolerating fences or surrounding model prose."""

    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as first_error:
        decoder = json.JSONDecoder()
        for index, character in enumerate(stripped):
            if character not in "[{\"-0123456789tfn":
                continue
            try:
                value, _ = decoder.raw_decode(stripped[index:])
            except json.JSONDecodeError:
                continue
            return value
        raise first_error


def _reasoning_config(tier: ModelTier) -> dict[str, object] | None:
    if tier is ModelTier.FAST:
        return {"enabled": False, "effort": "none"}
    return None


def _messages(system_prompt: str, prompt: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]


def _route_record(route: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (str(name), str(value))
            for name, value in route.items()
            if value is not None
        )
    )


async def _call_and_admit(
    *,
    role: ModelRole,
    system_prompt: str,
    prompt: str,
    admit: Callable[[object], T],
    options: CallOptions,
) -> _AttemptOutcome:
    auxiliary_task = _AUXILIARY_TASKS[(role, options.tier)]
    try:
        response = await call_model_transport(
            ModelTransportRequest(
                task=auxiliary_task,
                messages=tuple(_messages(system_prompt, prompt)),
                temperature=options.temperature,
                max_tokens=options.max_tokens,
                timeout=options.timeout,
                main_runtime=(
                    dict(options.main_runtime)
                    if options.main_runtime is not None
                    else None
                ),
                reasoning_config=_reasoning_config(options.tier),
            )
        )
    except Exception as exc:
        return _AttemptOutcome(
            failure=CallFailure(
                CallFailureKind.MODEL_CALL,
                f"{type(exc).__name__}: {exc}",
            ),
            auxiliary_task=auxiliary_task,
            route=_route_record(getattr(exc, "route", {})),
        )

    route_record = _route_record(response.route)
    raw_response = response.text
    if not raw_response:
        return _AttemptOutcome(
            failure=CallFailure(
                CallFailureKind.EMPTY_RESPONSE,
                "model response contained no text",
            ),
            auxiliary_task=auxiliary_task,
            route=route_record,
        )
    try:
        payload = _parse_json(raw_response)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return _AttemptOutcome(
            failure=CallFailure(
                CallFailureKind.INVALID_JSON,
                f"{type(exc).__name__}: {exc}",
            ),
            raw_response=raw_response,
            auxiliary_task=auxiliary_task,
            route=route_record,
        )
    try:
        value = admit(payload)
    except (TypeError, ValueError, KeyError) as exc:
        return _AttemptOutcome(
            failure=CallFailure(
                CallFailureKind.ADMISSION_REJECTED,
                f"{type(exc).__name__}: {exc}",
            ),
            raw_response=raw_response,
            auxiliary_task=auxiliary_task,
            route=route_record,
        )
    return _AttemptOutcome(
        value=value,
        raw_response=raw_response,
        auxiliary_task=auxiliary_task,
        route=route_record,
    )


def _trace(
    outcome: _AttemptOutcome,
    *,
    role: ModelRole,
    tier: ModelTier,
) -> CallTrace:
    return CallTrace(
        role=role,
        tier=tier,
        auxiliary_task=outcome.auxiliary_task,
        route=outcome.route,
    )


async def structured_json_completion(
    request: StructuredJSONRequest[T],
) -> StructuredJSONResult[T]:
    """Make one auxiliary call and admit one Episode-defined JSON shape."""

    if not isinstance(request, StructuredJSONRequest):
        raise TypeError("request must be StructuredJSONRequest")
    outcome = await _call_and_admit(
        role=ModelRole.STRUCTURED_JSON,
        system_prompt=request.system_prompt,
        prompt=request.prompt,
        admit=request.admit,
        options=request.options,
    )
    return StructuredJSONResult(
        value=outcome.value,
        failure=outcome.failure,
        trace=_trace(
            outcome,
            role=ModelRole.STRUCTURED_JSON,
            tier=request.options.tier,
        ),
        raw_response=outcome.raw_response,
    )


def _probability(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("admitted probability must be numeric")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError("admitted probability must be between zero and one")
    return result


async def probability_judgment(
    request: ProbabilityJudgmentRequest,
) -> ProbabilityJudgmentResult:
    """Return one admitted probability without choosing an Episode action."""

    if not isinstance(request, ProbabilityJudgmentRequest):
        raise TypeError("request must be ProbabilityJudgmentRequest")

    def admit(payload: object) -> float:
        return _probability(request.admit(payload))

    outcome = await _call_and_admit(
        role=ModelRole.PROBABILITY,
        system_prompt=request.system_prompt,
        prompt=request.prompt,
        admit=admit,
        options=request.options,
    )
    return ProbabilityJudgmentResult(
        probability=outcome.value,
        failure=outcome.failure,
        trace=_trace(
            outcome,
            role=ModelRole.PROBABILITY,
            tier=request.options.tier,
        ),
        raw_response=outcome.raw_response,
    )


async def probability_vector_judgment(
    request: ProbabilityVectorJudgmentRequest,
) -> ProbabilityVectorJudgmentResult:
    """Return named admitted probabilities from one shared Episode prompt."""

    if not isinstance(request, ProbabilityVectorJudgmentRequest):
        raise TypeError("request must be ProbabilityVectorJudgmentRequest")

    def admit(payload: object) -> dict[str, float]:
        raw = request.admit(payload)
        if not isinstance(raw, Mapping) or not raw:
            raise ValueError("admitted probability vector must be a non-empty mapping")
        result: dict[str, float] = {}
        for name, value in raw.items():
            key = str(name).strip()
            if not key:
                raise ValueError("probability vector names must be non-empty")
            result[key] = _probability(value)
        return result

    outcome = await _call_and_admit(
        role=ModelRole.PROBABILITY,
        system_prompt=request.system_prompt,
        prompt=request.prompt,
        admit=admit,
        options=request.options,
    )
    return ProbabilityVectorJudgmentResult(
        probabilities=outcome.value,
        failure=outcome.failure,
        trace=_trace(
            outcome,
            role=ModelRole.PROBABILITY,
            tier=request.options.tier,
        ),
        raw_response=outcome.raw_response,
    )


__all__ = [
    "probability_judgment",
    "probability_vector_judgment",
    "structured_json_completion",
]
