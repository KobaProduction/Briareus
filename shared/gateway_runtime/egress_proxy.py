"""TCP proxy adapter for bounded public-only Node egress."""

from __future__ import annotations

import asyncio
import socket

from gateway_runtime.application.egress import (
    ByteReader,
    ByteWriter,
    ConnectPublicDestination,
    PublicConnection,
)
from gateway_runtime.domain.egress import PublicDestination, loopback_peer, parse_proxy_header


class AsyncioPublicConnector:
    async def resolve(self, destination: PublicDestination) -> tuple[str, ...]:
        resolved = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(
                destination.host, destination.port, type=socket.SOCK_STREAM
            ),
            5,
        )
        addresses: list[str] = []
        for item in resolved:
            address = item[4][0]
            if not isinstance(address, str):
                raise ValueError("Private or mixed DNS destination denied")
            addresses.append(address)
        return tuple(addresses)

    async def dial(self, address: str, port: int) -> PublicConnection:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(address, port), 8)
        return PublicConnection(reader, writer)


async def public_connection(host: str, port: int) -> PublicConnection:
    return await ConnectPublicDestination(AsyncioPublicConnector()).execute(
        PublicDestination(host, port)
    )


async def relay(reader: ByteReader, writer: ByteWriter) -> None:
    total = 0
    while True:
        chunk = await asyncio.wait_for(reader.read(65536), 30)
        if not chunk:
            return
        total += len(chunk)
        if total > 16 * 1024 * 1024:
            raise ValueError("Public egress connection budget exceeded")
        writer.write(chunk)
        await writer.drain()


async def _readiness(writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    if not peer or not loopback_peer(peer[0]):
        raise ValueError("Proxy readiness is local only")
    body = b'{"state":"ready","egress":"public_only"}'
    writer.write(
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n"
        b"Connection: close\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
    )
    await writer.drain()


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    upstream: ByteWriter | None = None
    tasks: list[asyncio.Task[None]] = []
    try:
        header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        request = parse_proxy_header(header)
        if request is None:
            await _readiness(writer)
            return
        remote, upstream = await public_connection(
            request.destination.host, request.destination.port
        )
        if request.preface is None:
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        else:
            upstream.write(request.preface)
            await upstream.drain()
        await writer.drain()
        tasks = [
            asyncio.create_task(relay(reader, upstream)),
            asyncio.create_task(relay(remote, writer)),
        ]
        await asyncio.wait(tasks, timeout=60, return_when=asyncio.FIRST_COMPLETED)
    except (
        ValueError,
        OSError,
        TimeoutError,
        asyncio.IncompleteReadError,
        asyncio.LimitOverrunError,
    ):
        if not writer.is_closing():
            writer.write(
                b"HTTP/1.1 502 Public destination unavailable\r\nContent-Length: 0\r\n"
                b"Connection: close\r\n\r\n"
            )
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if upstream is not None:
            upstream.close()
        writer.close()


async def main() -> None:
    gate = asyncio.Semaphore(32)

    async def bounded(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async with gate:
            await handle(reader, writer)

    server = await asyncio.start_server(
        bounded,
        "0.0.0.0",
        8080,
        limit=16384,  # noqa: S104 -- existing Node egress network listener
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
