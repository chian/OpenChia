"""Typed inputs and outcomes for reusable Episode model calls."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Generic, Mapping, Protocol, TypeVar, runtime_checkable


T = TypeVar("T")


class ModelRole(str, Enum):
    """Why a model is being called, independent of its provider or model ID."""

    STRUCTURED_JSON = "structured-json"
    PROBABILITY = "probability"


class ModelTier(str, Enum):
    """The Episode-declared model class; concrete routing remains configuration."""

    REASONING = "reasoning"
    FAST = "fast"


class CallFailureKind(str, Enum):
    MODEL_CALL = "model-call"
    EMPTY_RESPONSE = "empty-response"
    INVALID_JSON = "invalid-json"
    ADMISSION_REJECTED = "admission-rejected"


@runtime_checkable
class ResponseAdmission(Protocol[T]):
    """Episode-owned semantic validation of one parsed JSON response."""

    def __call__(self, payload: object) -> T: ...


@runtime_checkable
class ProbabilityAdmission(Protocol):
    """Episode-owned projection of one parsed JSON response to a probability."""

    def __call__(self, payload: object) -> float: ...


@runtime_checkable
class ProbabilityVectorAdmission(Protocol):
    """Episode-owned projection to named probabilities."""

    def __call__(self, payload: object) -> Mapping[str, float]: ...


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be non-empty text")
    return value


@dataclass(frozen=True)
class CallOptions:
    """Provider-neutral controls shared by all three call shapes."""

    model_type: str
    tier: ModelTier = ModelTier.REASONING
    temperature: float | None = None
    max_tokens: int | None = None
    timeout: float | None = None
    main_runtime: Mapping[str, Any] | None = None
    launch_configuration_hash: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.tier, ModelTier):
            raise TypeError("tier must be a ModelTier")
        _text(self.model_type, "model_type")
        if self.launch_configuration_hash is not None:
            _text(self.launch_configuration_hash, "launch_configuration_hash")
        if self.max_tokens is not None and (
            isinstance(self.max_tokens, bool)
            or not isinstance(self.max_tokens, int)
            or self.max_tokens < 1
        ):
            raise ValueError("max_tokens must be a positive integer or None")
        if self.timeout is not None and self.timeout <= 0:
            raise ValueError("timeout must be positive or None")
        if self.main_runtime is not None:
            if not isinstance(self.main_runtime, Mapping):
                raise TypeError("main_runtime must be a mapping or None")
            object.__setattr__(
                self,
                "main_runtime",
                MappingProxyType(dict(self.main_runtime)),
            )


@dataclass(frozen=True)
class StructuredJSONRequest(Generic[T]):
    system_prompt: str
    prompt: str
    admit: ResponseAdmission[T]
    options: CallOptions

    def __post_init__(self) -> None:
        _text(self.system_prompt, "system_prompt")
        _text(self.prompt, "prompt")
        if not callable(self.admit):
            raise TypeError("admit must be callable")
        if not isinstance(self.options, CallOptions):
            raise TypeError("options must be CallOptions")


@dataclass(frozen=True)
class ProbabilityJudgmentRequest:
    system_prompt: str
    prompt: str
    admit: ProbabilityAdmission
    options: CallOptions

    def __post_init__(self) -> None:
        _text(self.system_prompt, "system_prompt")
        _text(self.prompt, "prompt")
        if not callable(self.admit):
            raise TypeError("admit must be callable")
        if not isinstance(self.options, CallOptions):
            raise TypeError("options must be CallOptions")


@dataclass(frozen=True)
class ProbabilityVectorJudgmentRequest:
    system_prompt: str
    prompt: str
    admit: ProbabilityVectorAdmission
    options: CallOptions

    def __post_init__(self) -> None:
        _text(self.system_prompt, "system_prompt")
        _text(self.prompt, "prompt")
        if not callable(self.admit):
            raise TypeError("admit must be callable")
        if not isinstance(self.options, CallOptions):
            raise TypeError("options must be CallOptions")


@dataclass(frozen=True)
class CallTrace:
    """Provider-neutral selection plus the existing boundary's route receipt."""

    role: ModelRole
    tier: ModelTier
    auxiliary_task: str
    route: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class CallFailure:
    kind: CallFailureKind
    message: str


@dataclass(frozen=True)
class StructuredJSONResult(Generic[T]):
    value: T | None
    failure: CallFailure | None
    trace: CallTrace
    raw_response: str = ""

    @property
    def succeeded(self) -> bool:
        return self.failure is None


@dataclass(frozen=True)
class ProbabilityJudgmentResult:
    probability: float | None
    failure: CallFailure | None
    trace: CallTrace
    raw_response: str = ""

    @property
    def succeeded(self) -> bool:
        return self.failure is None


@dataclass(frozen=True)
class ProbabilityVectorJudgmentResult:
    probabilities: Mapping[str, float] | None
    failure: CallFailure | None
    trace: CallTrace
    raw_response: str = ""

    def __post_init__(self) -> None:
        if self.probabilities is not None:
            object.__setattr__(
                self,
                "probabilities",
                MappingProxyType(dict(self.probabilities)),
            )

    @property
    def succeeded(self) -> bool:
        return self.failure is None


__all__ = [
    "CallFailure",
    "CallFailureKind",
    "CallOptions",
    "CallTrace",
    "ModelRole",
    "ModelTier",
    "ProbabilityAdmission",
    "ProbabilityJudgmentRequest",
    "ProbabilityJudgmentResult",
    "ProbabilityVectorAdmission",
    "ProbabilityVectorJudgmentRequest",
    "ProbabilityVectorJudgmentResult",
    "ResponseAdmission",
    "StructuredJSONRequest",
    "StructuredJSONResult",
]
