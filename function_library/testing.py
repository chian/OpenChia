"""One worker client for the same experiment service used by the CLI."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Mapping

from .models import FunctionImplementation, LibraryFunction
from .registry import FunctionLibrary
from .testing_contract import OPERATIONS


_transport = ContextVar("openchia_experiment_transport", default=None)


@contextmanager
def experiment_transport_scope(transport):
    token = _transport.set(transport)
    try:
        yield
    finally:
        _transport.reset(token)


async def experiment_request(*, operation, payload):
    if operation not in OPERATIONS or not isinstance(payload, Mapping):
        raise ValueError("unknown experimental operation or invalid payload")
    transport = _transport.get()
    if transport is None:
        raise RuntimeError("experiments require the approved host/worker channel")
    result = await transport(operation, payload)
    if not isinstance(result, Mapping):
        raise ValueError("experiment host returned an invalid response")
    return result


testing_function_library = FunctionLibrary()
EXPERIMENT_REQUEST = testing_function_library.register(
    LibraryFunction(
        library="testing",
        function_id="experiment_request_v1",
        interface="testing.request",
        description="Design, preview, execute and inspect experiments through the unified host service under exact human-approved testing access.",
        implementation=FunctionImplementation(
            module="function_library.testing",
            symbol="experiment_request",
            is_async=True,
        ),
        input_type="operation and typed payload; describe returns available schemas and assigned targets",
        output_type="Structured experiment plan, result, comparison or explicit rejection",
        effect="Host-mediated testing only; grants no editing, child-creation, measurement-registration or acceptance authority.",
        failure_contract="Reject requests outside the frozen testing contract; no scope widening, live replay fallback or self-awarded credit.",
        provenance={
            "schema_version": 1,
            "parameter_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    )
)


def _adapter(
    function_id, interface, module, symbol, description, *, model_slot_parameters=()
):
    return testing_function_library.register(
        LibraryFunction(
            library="testing",
            function_id=function_id,
            interface=interface,
            description=description,
            implementation=FunctionImplementation(
                module=module, symbol=symbol, is_async=False
            ),
            input_type="Frozen contract and typed experimental evidence",
            output_type="Typed testing Episode state",
            effect="Use the shared experiment service and existing host learning controller.",
            failure_contract="No worker-awarded credit, modified criteria or implicit acceptance.",
            provenance={
                "version": 1,
                **({"model_slot_parameters": list(model_slot_parameters)} if model_slot_parameters else {}),
                "parameter_schema": {
                    "type": "object",
                    "properties": {
                        parameter: {"type": "string"}
                        for parameter in model_slot_parameters
                    },
                    **({"required": list(model_slot_parameters)} if model_slot_parameters else {}),
                    "additionalProperties": False,
                },
            },
        )
    )


OPEN_SOURCE = _adapter(
    "open_testing_source_v1",
    "episode.unit_source",
    "function_library.testing_source",
    "open_testing_source",
    "Choose experiments adaptively using measured evidence.",
    model_slot_parameters=("selection_model_type", "execution_model_type"),
)
ADMISSION = _adapter(
    "admit_testing_findings_v1",
    "epistemic.admission",
    "function_library.testing_admission",
    "admit_testing_findings",
    "Admit distinct exact host-measured requirement outcomes, not model judgments.",
)
RESULT_PROJECTION = _adapter(
    "project_testing_findings_v1",
    "epistemic.result_projection",
    "function_library.testing_admission",
    "project_testing_findings",
    "Return supported experimental findings without parent acceptance authority.",
)
