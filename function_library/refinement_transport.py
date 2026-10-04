"""One scoped host-operation channel shared by all refinement Episodes."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Mapping

from .refinement_contract import OPERATIONS


_transport = ContextVar("openchia_refinement_transport", default=None)


@contextmanager
def refinement_transport_scope(transport):
    token = _transport.set(transport)
    try:
        yield
    finally:
        _transport.reset(token)


async def exchange(operation, payload):
    if operation not in OPERATIONS or not isinstance(payload, Mapping):
        raise ValueError("unknown refinement operation or invalid request")
    transport = _transport.get()
    if transport is None:
        raise RuntimeError("refinement requires an explicitly admitted host session")
    response = await transport(operation, payload)
    if not isinstance(response, Mapping):
        raise ValueError("refinement host returned an invalid response")
    return response
