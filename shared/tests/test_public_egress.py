"""Public-only DNS and HTTP read contracts without opening external connections."""

from __future__ import annotations

import unittest

from gateway_runtime.application.egress import ConnectPublicDestination, PublicConnection
from gateway_runtime.domain.egress import PublicDestination, parse_proxy_header, public_addresses


class MemoryReader:
    def __init__(self) -> None:
        self.data = b""

    async def read(self, n: int = -1) -> bytes:
        chunk = self.data[:n] if n >= 0 else self.data
        self.data = self.data[len(chunk) :]
        return chunk


class MemoryWriter:
    def write(self, data: bytes) -> None:
        pass

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        pass


class Connector:
    def __init__(self, addresses: tuple[str, ...]) -> None:
        self.addresses = addresses
        self.resolutions: list[PublicDestination] = []
        self.dials: list[tuple[str, int]] = []

    async def resolve(self, destination: PublicDestination) -> tuple[str, ...]:
        self.resolutions.append(destination)
        return self.addresses

    async def dial(self, address: str, port: int) -> PublicConnection:
        self.dials.append((address, port))
        if address == "1.1.1.1":
            raise OSError("fixture connection refused")
        return PublicConnection(MemoryReader(), MemoryWriter())


class PublicEgressPolicyTests(unittest.TestCase):
    def test_complete_dns_answer_must_be_public_unicast_and_deterministic(self) -> None:
        self.assertEqual(
            public_addresses(("8.8.8.8", "1.1.1.1", "8.8.8.8")), ("1.1.1.1", "8.8.8.8")
        )
        for addresses in (
            (),
            ("127.0.0.1",),
            ("::1",),
            ("169.254.169.254",),
            ("8.8.8.8", "10.0.0.1"),
            ("224.0.0.1",),
            ("240.0.0.1",),
        ):
            with self.subTest(addresses=addresses), self.assertRaises(ValueError):
                public_addresses(addresses)

    def test_http_read_rewrites_host_and_drops_proxy_credentials_and_hop_headers(self) -> None:
        request = parse_proxy_header(
            b"GET http://example.com:80/path?q=1 HTTP/1.0\r\nHost: wrong.example\r\n"
            b"Proxy-Authorization: private\r\nConnection: keep-alive\r\n"
            b"Proxy-Connection: keep-alive\r\nAccept: application/json\r\n\r\n"
        )
        self.assertIsNotNone(request)
        if request is None:
            raise AssertionError("HTTP request was classified as readiness")
        self.assertEqual(request.destination, PublicDestination("example.com", 80))
        self.assertEqual(
            request.preface,
            b"GET /path?q=1 HTTP/1.1\r\nHost: example.com:80\r\n"
            b"Connection: close\r\nAccept: application/json\r\n\r\n",
        )

    def test_only_exact_https_connect_and_body_free_http_reads_are_accepted(self) -> None:
        tunnel = parse_proxy_header(b"CONNECT example.com:443 HTTP/1.1\r\n\r\n")
        self.assertIsNotNone(tunnel)
        if tunnel is None:
            raise AssertionError("CONNECT request was classified as readiness")
        self.assertEqual(tunnel.destination, PublicDestination("example.com", 443))
        self.assertIsNone(tunnel.preface)
        self.assertIsNone(parse_proxy_header(b"GET /health/ready HTTP/1.1\r\n\r\n"))
        for request in (
            b"CONNECT example.com:80 HTTP/1.1\r\n\r\n",
            b"CONNECT example.com:443/path HTTP/1.1\r\n\r\n",
            b"CONNECT user@example.com:443 HTTP/1.1\r\n\r\n",
            b"POST http://example.com HTTP/1.1\r\n\r\n",
            b"GET https://example.com HTTP/1.1\r\n\r\n",
            b"GET http://example.com HTTP/2\r\n\r\n",
            b"GET http://example.com HTTP/1.1\r\nContent-Length: 0\r\n\r\n",
            b"GET http://example.com HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n",
            b"GET http://example.com HTTP/1.1\r\nUpgrade: websocket\r\n\r\n",
            b"GET http://example.com HTTP/1.1\r\nAccept: a\r\naccept: b\r\n\r\n",
            b"GET http://example.com HTTP/1.1\r\nBad Name: value\r\n\r\n",
        ):
            with self.subTest(request=request), self.assertRaises(ValueError):
                parse_proxy_header(request)


class PublicEgressScenarioTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_resolution_pinned_numeric_fallback_in_sorted_order(self) -> None:
        connector = Connector(("8.8.8.8", "1.1.1.1"))
        destination = PublicDestination("example.com", 443)
        connection = await ConnectPublicDestination(connector).execute(destination)
        self.assertIsInstance(connection.reader, MemoryReader)
        self.assertEqual(connector.resolutions, [destination])
        self.assertEqual(connector.dials, [("1.1.1.1", 443), ("8.8.8.8", 443)])

    async def test_mixed_resolution_never_dials_even_public_address(self) -> None:
        connector = Connector(("8.8.8.8", "127.0.0.1"))
        with self.assertRaisesRegex(ValueError, "Private or mixed DNS destination denied"):
            await ConnectPublicDestination(connector).execute(PublicDestination("example.com", 80))
        self.assertEqual(connector.dials, [])
