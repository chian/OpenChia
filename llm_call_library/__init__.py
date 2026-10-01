"""Reusable, typed LLM call mechanics for explicitly composed Episodes."""

from .calls import (
    probability_judgment,
    probability_vector_judgment,
    structured_json_completion,
)
from .contracts import (
    CallFailure,
    CallFailureKind,
    CallOptions,
    CallTrace,
    ModelRole,
    ModelTier,
    ProbabilityAdmission,
    ProbabilityJudgmentRequest,
    ProbabilityJudgmentResult,
    ProbabilityVectorAdmission,
    ProbabilityVectorJudgmentRequest,
    ProbabilityVectorJudgmentResult,
    ResponseAdmission,
    StructuredJSONRequest,
    StructuredJSONResult,
)
from .definitions import (
    PROBABILITY_JUDGMENT,
    PROBABILITY_VECTOR_JUDGMENT,
    STRUCTURED_JSON_COMPLETION,
)
from .transport import (
    ModelTransport,
    ModelTransportRequest,
    ModelTransportResponse,
    call_model_transport,
    model_transport_scope,
)


__all__ = [
    "CallFailure",
    "CallFailureKind",
    "CallOptions",
    "CallTrace",
    "ModelRole",
    "ModelTier",
    "ModelTransport",
    "ModelTransportRequest",
    "ModelTransportResponse",
    "PROBABILITY_JUDGMENT",
    "PROBABILITY_VECTOR_JUDGMENT",
    "ProbabilityAdmission",
    "ProbabilityJudgmentRequest",
    "ProbabilityJudgmentResult",
    "ProbabilityVectorAdmission",
    "ProbabilityVectorJudgmentRequest",
    "ProbabilityVectorJudgmentResult",
    "ResponseAdmission",
    "STRUCTURED_JSON_COMPLETION",
    "StructuredJSONRequest",
    "StructuredJSONResult",
    "call_model_transport",
    "model_transport_scope",
    "probability_judgment",
    "probability_vector_judgment",
    "structured_json_completion",
]
