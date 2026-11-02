"""Local dial override cannot alter the approved TLS identity or HTTP authority."""

import os
import unittest
from unittest.mock import patch

import httpx
from bridge._local_node_transport import LocalNodeTransport, local_node_transport


class LocalNodeTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_dial_retains_body_authority_and_tls_hostname(self) -> None:
        transport = LocalNodeTransport.__new__(LocalNodeTransport)

        def receive(request: httpx.Request) -> httpx.Response:
            self.assertEqual(str(request.url), "https://local-node-tls/internal/v1/node/mcp")
            self.assertEqual(request.headers["host"], "127.0.0.2")
            self.assertEqual(request.extensions["sni_hostname"], "127.0.0.2")
            self.assertEqual(request.content, b"request-body")
            return httpx.Response(200, json={"status": "fixture"})

        with (
            patch.object(transport, "inner", httpx.MockTransport(receive), create=True),
        ):
            async with httpx.AsyncClient(transport=transport) as client:
                self.assertEqual(
                    (
                        await client.post(
                            "https://127.0.0.2/internal/v1/node/mcp", content=b"request-body"
                        )
                    ).status_code,
                    200,
                )
                for url in [
                    "http://127.0.0.2/",
                    "https://other.example/",
                    "https://127.0.0.2:444/",
                ]:
                    with self.assertRaises(ValueError):
                        await client.get(url)

    async def test_override_is_disabled_without_explicit_local_adapter(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(local_node_transport())
        with (
            patch.dict(os.environ, {"BRIAREUS_LOCAL_NODE_DIAL": "local-node-tls:443"}, clear=True),
            self.assertRaises(ValueError),
        ):
            local_node_transport()
