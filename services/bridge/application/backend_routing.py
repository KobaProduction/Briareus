"""Backend availability discovery, independent of MCP schemas and results."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class BackendLocation:
    name: str
    public_path: str
    purpose: str


@dataclass(frozen=True, slots=True)
class BackendStatus:
    location: BackendLocation
    status: Literal["available", "not_available"]
    tool_count: int
    error_type: str | None = None


class BackendPort(Protocol):
    async def tool_count(self, name: str) -> int: ...


class BackendRouting:
    def __init__(self, backends: tuple[BackendLocation, ...], port: BackendPort) -> None:
        self._backends = {backend.name: backend for backend in backends}
        self._port = port

    def location(self, name: str) -> BackendLocation:
        backend = self._backends.get(name.strip().casefold())
        if backend is None:
            raise ValueError(f"unknown backend {name!r}; expected one of {sorted(self._backends)}")
        return backend

    async def describe(self) -> tuple[BackendStatus, ...]:
        return tuple(
            await asyncio.gather(*(self._probe(backend) for backend in self._backends.values()))
        )

    async def _probe(self, backend: BackendLocation) -> BackendStatus:
        try:
            count = await self._port.tool_count(backend.name)
        except Exception as exc:
            return BackendStatus(backend, "not_available", 0, type(exc).__name__)
        return BackendStatus(backend, "available", count)
