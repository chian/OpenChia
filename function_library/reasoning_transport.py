"""Typed asynchronous host exchange; no filesystem or host state in a worker."""

from contextlib import contextmanager
from contextvars import ContextVar


_transport = ContextVar("openchia_reasoning_transport", default=None)


@contextmanager
def reasoning_transport_scope(transport):
    token = _transport.set(transport)
    try:
        yield
    finally:
        _transport.reset(token)


async def exchange(operation, payload):
    transport = _transport.get()
    if transport is None:
        raise RuntimeError("reasoning requires the admitted host learning boundary")
    return await transport(operation, payload)
