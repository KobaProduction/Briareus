"""Build the common SDK proxy for an explicit Web target; policies stay with adapters."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Literal

from fastmcp import FastMCP
from fastmcp.client.transports import ClientTransport
from fastmcp.server.providers.proxy import FastMCPProxy, ProxyClient


def browser_proxy[AppState, TransportT: ClientTransport](
    *,
    target: Literal["internal", "external"],
    client_factory: Callable[[], ProxyClient[TransportT]]
    | Callable[[], Awaitable[ProxyClient[TransportT]]],
    lifespan: Callable[[FastMCP[AppState]], AbstractAsyncContextManager[None]] | None = None,
) -> FastMCP[AppState]:
    if target == "internal":
        name = "chrome-devtools-upstream"
    elif target == "external":
        name = "external-playwright-upstream"
    else:
        raise ValueError("Unknown browser proxy target")
    if lifespan is None:
        return FastMCPProxy(
            client_factory=client_factory,
            name=name,
            provider_error_strategy="warn",
            identity="upstream",
        )
    return FastMCPProxy(
        client_factory=client_factory,
        name=name,
        provider_error_strategy="warn",
        identity="upstream",
        lifespan=lifespan,
    )
