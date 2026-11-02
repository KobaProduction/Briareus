"""Typed access to the pinned grpcio-health-checking AsyncIO implementation.

The upstream health module exports this implementation as ``health.aio``;
its distributed stubs currently describe only the synchronous service.
"""

from importlib import import_module
from typing import Protocol, cast


class AsyncHealthService(Protocol):
    async def set(self, service: str, status: int) -> None: ...


class AsyncHealthModule(Protocol):
    def HealthServicer(self) -> AsyncHealthService: ...


def create_async_health() -> AsyncHealthService:
    implementation = cast(AsyncHealthModule, import_module("grpc_health.v1._async"))
    return implementation.HealthServicer()
