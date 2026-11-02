"""Pinned FastMCP connection hooks used by the Bridge's persistent sessions.

The SDK leaves these hooks unannotated. Their actual signatures are kept here;
the proxy's two connection holds and force-close semantics remain unchanged.
"""

from collections.abc import Awaitable, Callable
from typing import Protocol

from fastmcp import Client, FastMCP
from fastmcp.client.transports import ClientTransport

type BackendTarget[LifespanT] = str | FastMCP[LifespanT]
type TimeoutProvider = Callable[[], Awaitable[float]]


class SdkSessionLifecycle(Protocol):
    async def _connect(self) -> Client[ClientTransport]: ...

    async def _disconnect(self, force: bool = False) -> None: ...
