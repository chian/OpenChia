"""HTTP client settings for pinned provider connections.

A model request may legitimately stay silent for many minutes (some gateways,
such as ANL's Argo, send a long completion only when it is finished), so there
is deliberately no read timeout. What must not happen is waiting forever on a
connection whose peer has gone away without a FIN or RST, as when a VPN drops
mid-request (#77). TCP keepalive probes a silent connection at the transport
layer: a live peer acknowledges them without sending data, a vanished one does
not, and the blocked read then fails with a read error the recovery supervisor
can classify and replace (ADR 0008 amendment).
"""

from __future__ import annotations

import socket

#: Seconds of silence before the first keepalive probe, the interval between
#: probes, and how many unanswered probes declare the peer dead (~2 minutes).
KEEPALIVE_IDLE_SECONDS = 60
KEEPALIVE_INTERVAL_SECONDS = 15
KEEPALIVE_PROBES = 4
#: Bound establishing a connection; reading stays unbounded (see module docstring).
CONNECT_TIMEOUT_SECONDS = 30.0


def keepalive_socket_options() -> list[tuple[int, int, int]]:
    """``setsockopt`` triples enabling TCP keepalive with the module's timing."""
    options = [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
    # Linux names the idle setting TCP_KEEPIDLE; macOS names it TCP_KEEPALIVE.
    idle = getattr(socket, "TCP_KEEPIDLE", None) or getattr(socket, "TCP_KEEPALIVE", None)
    if idle is not None:
        options.append((socket.IPPROTO_TCP, idle, KEEPALIVE_IDLE_SECONDS))
    for name, value in (("TCP_KEEPINTVL", KEEPALIVE_INTERVAL_SECONDS), ("TCP_KEEPCNT", KEEPALIVE_PROBES)):
        constant = getattr(socket, name, None)
        if constant is not None:
            options.append((socket.IPPROTO_TCP, constant, value))
    return options


def provider_http_client(**kwargs):
    """An ``httpx.Client`` for one pinned provider call: keepalive, bounded connect, no read timeout."""
    import httpx

    kwargs.setdefault("timeout", httpx.Timeout(None, connect=CONNECT_TIMEOUT_SECONDS))
    return httpx.Client(transport=httpx.HTTPTransport(socket_options=keepalive_socket_options()), **kwargs)


__all__ = ["CONNECT_TIMEOUT_SECONDS", "keepalive_socket_options", "provider_http_client"]
