"""Resolve once, authorize the complete answer, then dial only pinned addresses."""

from __future__ import annotations

from typing import NamedTuple, Protocol

from gateway_runtime.domain.egress import PublicDestination, public_addresses


class ByteReader(Protocol):
    async def read(self, n: int = -1) -> bytes: ...


class ByteWriter(Protocol):
    def write(self, data: bytes) -> None: ...

    async def drain(self) -> None: ...

    def close(self) -> None: ...


class PublicConnection(NamedTuple):
    reader: ByteReader
    writer: ByteWriter


class PublicConnector(Protocol):
    async def resolve(self, destination: PublicDestination) -> tuple[str, ...]: ...

    async def dial(self, address: str, port: int) -> PublicConnection: ...


class ConnectPublicDestination:
    def __init__(self, connector: PublicConnector) -> None:
        self.connector = connector

    async def execute(self, destination: PublicDestination) -> PublicConnection:
        resolved = await self.connector.resolve(destination)
        for address in public_addresses(resolved):
            try:
                return await self.connector.dial(address, destination.port)
            except OSError:
                continue
        raise ValueError("Destination unavailable")
