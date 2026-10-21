"""Public-only Node egress; no Core network, credentials, data or engine socket.

Resolve once, reject private/mixed DNS answers, then dial a verified numeric
address. HTTPS remains end-to-end between the executor and the destination.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


async def public_connection(host: str, port: int):
    if not host or len(host) > 253 or port not in {80, 443} or "%" in host:
        raise ValueError("Unsupported public destination")
    resolved = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM), 5)
    addresses = {item[4][0] for item in resolved}
    if not addresses or any(not ipaddress.ip_address(address).is_global
                            or ipaddress.ip_address(address).is_multicast
                            or ipaddress.ip_address(address).is_reserved for address in addresses):
        raise ValueError("Private or mixed DNS destination denied")
    for address in sorted(addresses):
        try:
            return await asyncio.wait_for(asyncio.open_connection(address, port), 8)
        except OSError:
            continue
    raise ValueError("Destination unavailable")


async def relay(reader, writer):
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


async def handle(reader, writer):
    upstream = None
    tasks = []
    try:
        header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        if len(header) > 16384:
            raise ValueError("Proxy header too large")
        lines = header.decode("iso-8859-1").split("\r\n")
        method, target, version = lines[0].split(" ")
        if version not in {"HTTP/1.0", "HTTP/1.1"}:
            raise ValueError("Unsupported proxy protocol")
        if method == "GET" and target == "/health/ready":
            peer = writer.get_extra_info("peername")
            if not peer or not ipaddress.ip_address(peer[0]).is_loopback:
                raise ValueError("Proxy readiness is local only")
            body = b'{"state":"ready","egress":"public_only"}'
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n"
                         b"Connection: close\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
            await writer.drain()
            return
        if method == "CONNECT":
            url = urlsplit("https://" + target)
            if url.port != 443 or url.path or url.query or url.fragment or url.username or url.password:
                raise ValueError("Exact HTTPS authority required")
            remote, upstream = await public_connection(url.hostname, 443)
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        else:
            url = urlsplit(target)
            if (url.scheme != "http" or url.port not in {None, 80} or url.username or url.password
                or method not in {"GET", "HEAD"}):
                raise ValueError("Only public HTTP reads are supported")
            remote, upstream = await public_connection(url.hostname, 80)
            headers = []
            seen = set()
            for line in lines[1:-2]:
                name, value = line.split(":", 1)
                key = name.lower()
                if key in seen or not name or any(ch.isspace() for ch in name):
                    raise ValueError("Invalid proxy header")
                seen.add(key)
                if key in {"content-length", "transfer-encoding", "upgrade"}:
                    raise ValueError("HTTP body or upgrade denied")
                if key not in {"host", "connection", "proxy-connection", "proxy-authorization"}:
                    headers.append(line)
            path = (url.path or "/") + ("?" + url.query if url.query else "")
            request = [method + " " + path + " HTTP/1.1", "Host: " + url.netloc,
                       "Connection: close", *headers, "", ""]
            upstream.write("\r\n".join(request).encode("iso-8859-1"))
            await upstream.drain()
        await writer.drain()
        tasks = [asyncio.create_task(relay(reader, upstream)), asyncio.create_task(relay(remote, writer))]
        await asyncio.wait(tasks, timeout=60, return_when=asyncio.FIRST_COMPLETED)
    except (ValueError, OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        if not writer.is_closing():
            writer.write(b"HTTP/1.1 502 Public destination unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if upstream is not None:
            upstream.close()
        writer.close()


async def main():
    gate = asyncio.Semaphore(32)

    async def bounded(reader, writer):
        async with gate:
            await handle(reader, writer)

    server = await asyncio.start_server(bounded, "0.0.0.0", 8080, limit=16384)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
