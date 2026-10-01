"""Importable function objects used directly by Episode design modules."""

from __future__ import annotations

from types import MappingProxyType

from function_library import FunctionImplementation, LibraryFunction


_BOUNDARY = "agent.auxiliary_client.async_call_llm"


STRUCTURED_JSON_COMPLETION = LibraryFunction(
    library="llm_call_library",
    function_id="structured_json_completion",
    interface="llm.structured_json_completion",
    description=(
        "Run an Episode-supplied structured-JSON prompt and apply its imported "
        "response admission function."
    ),
    implementation=FunctionImplementation(
        module="llm_call_library.calls",
        symbol="structured_json_completion",
        is_async=True,
    ),
    input_type="llm_call_library.StructuredJSONRequest[T]",
    output_type="llm_call_library.StructuredJSONResult[T]",
    effect=(
        "An auxiliary model call through the existing routed, instrumented "
        "OpenChia client boundary."
    ),
    failure_contract=(
        "Returns a typed CallFailure from one auxiliary invocation; the client "
        "boundary owns transport retry and fallback, while cancellation and "
        "invalid caller types still raise."
    ),
    provenance=MappingProxyType(
        {
            "implementation_owner": "llm_call_library.calls.structured_json_completion",
            "client_boundary": _BOUNDARY,
            "prompt_owner": "binding Episode",
            "response_semantics_owner": "binding Episode admission callable",
        }
    ),
)


PROBABILITY_JUDGMENT = LibraryFunction(
    library="llm_call_library",
    function_id="probability_judgment",
    interface="llm.probability_judgment",
    description=(
        "Run an Episode-supplied probability prompt and return one admitted "
        "number in the closed interval zero to one."
    ),
    implementation=FunctionImplementation(
        module="llm_call_library.calls",
        symbol="probability_judgment",
        is_async=True,
    ),
    input_type="llm_call_library.ProbabilityJudgmentRequest",
    output_type="llm_call_library.ProbabilityJudgmentResult",
    effect=(
        "An auxiliary model call through the existing routed, instrumented "
        "OpenChia client boundary."
    ),
    failure_contract=(
        "Returns a typed CallFailure from one auxiliary invocation, including "
        "out-of-range probability rejection; the client boundary owns transport "
        "retry and fallback, while cancellation and invalid caller types raise."
    ),
    provenance=MappingProxyType(
        {
            "implementation_owner": "llm_call_library.calls.probability_judgment",
            "client_boundary": _BOUNDARY,
            "prompt_owner": "binding Episode",
            "response_semantics_owner": "binding Episode admission callable",
        }
    ),
)


PROBABILITY_VECTOR_JUDGMENT = LibraryFunction(
    library="llm_call_library",
    function_id="probability_vector_judgment",
    interface="llm.probability_vector_judgment",
    description=(
        "Run one Episode-supplied shared-state prompt and return its admitted "
        "mapping of named probabilities."
    ),
    implementation=FunctionImplementation(
        module="llm_call_library.calls",
        symbol="probability_vector_judgment",
        is_async=True,
    ),
    input_type="llm_call_library.ProbabilityVectorJudgmentRequest",
    output_type="llm_call_library.ProbabilityVectorJudgmentResult",
    effect=(
        "An auxiliary model call through the existing routed, instrumented "
        "OpenChia client boundary."
    ),
    failure_contract=(
        "Returns a typed CallFailure from one auxiliary invocation, including "
        "empty, unnamed, nonnumeric, or out-of-range vector rejection; the client "
        "boundary owns transport retry and fallback, while cancellation and "
        "invalid caller types raise."
    ),
    provenance=MappingProxyType(
        {
            "implementation_owner": "llm_call_library.calls.probability_vector_judgment",
            "client_boundary": _BOUNDARY,
            "prompt_owner": "binding Episode",
            "response_semantics_owner": "binding Episode admission callable",
        }
    ),
)


__all__ = [
    "PROBABILITY_JUDGMENT",
    "PROBABILITY_VECTOR_JUDGMENT",
    "STRUCTURED_JSON_COMPLETION",
]
