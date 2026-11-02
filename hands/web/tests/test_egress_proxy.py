"""Shared proxy DNS pinning plus real local TCP readiness/deny fixtures."""

from __future__ import annotations

import asyncio
import socket
import unittest
from unittest.mock import AsyncMock, patch

from gateway_runtime.egress_proxy import handle, public_connection


class PublicEgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_mixed_reserved_and_multicast_dns_never_connect(self) -> None:
        loop = asyncio.get_running_loop()
        for addresses in (
            ("127.0.0.1",),
            ("169.254.169.254",),
            ("10.0.0.1",),
            ("93.184.216.34", "192.168.1.1"),
            ("224.0.0.1",),
            ("::1",),
        ):
            resolved = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses
            ]
            with (
                patch.object(loop, "getaddrinfo", AsyncMock(return_value=resolved)),
                patch(
                    "gateway_runtime.egress_proxy.asyncio.open_connection", AsyncMock()
                ) as connect,
            ):
                with self.assertRaises(ValueError):
                    await public_connection("fixture.example", 443)
                connect.assert_not_awaited()

    async def test_verified_numeric_ip_is_dialed_without_hostname_relookup(self) -> None:
        loop = asyncio.get_running_loop()
        resolved = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        with (
            patch.object(loop, "getaddrinfo", AsyncMock(return_value=resolved)),
            patch(
                "gateway_runtime.egress_proxy.asyncio.open_connection",
                AsyncMock(return_value=("reader", "writer")),
            ) as connect,
        ):
            self.assertEqual(await public_connection("fixture.example", 443), ("reader", "writer"))
            connect.assert_awaited_once_with("93.184.216.34", 443)

    async def test_local_health_and_loopback_proxy_targets_over_real_tcp(self) -> None:
        server = await asyncio.start_server(handle, "127.0.0.1", 0, limit=16384)
        port = server.sockets[0].getsockname()[1]
        try:
            for request, expected in (
                (b"GET /health/ready HTTP/1.1\r\nHost: localhost\r\n\r\n", b"200 OK"),
                (b"CONNECT 127.0.0.1:443 HTTP/1.1\r\nHost: localhost\r\n\r\n", b"502"),
                (b"GET http://127.0.0.1/ HTTP/1.1\r\nHost: localhost\r\n\r\n", b"502"),
            ):
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.write(request)
                await writer.drain()
                response = await asyncio.wait_for(reader.read(), 2)
                writer.close()
                await writer.wait_closed()
                self.assertIn(expected, response.split(b"\r\n", 1)[0])
        finally:
            server.close()
            await server.wait_closed()


if __name__ == "__main__":
    unittest.main()
