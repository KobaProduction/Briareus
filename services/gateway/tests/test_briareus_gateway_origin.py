"""Public Gateway MCP host/origin policy comes from its sole canonical URL."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from gateway.gateway_settings import GatewayAuthSettings
from gateway.settings import GatewaySettings


class GatewayCanonicalOriginContracts(unittest.TestCase):
    def test_http_surface_uses_exact_host_and_origin(self) -> None:
        cases = (
            ("https://node.example", "node.example"),
            ("https://node.example:8443", "node.example:8443"),
            ("http://localhost:18080", "localhost:18080"),
            ("http://127.0.0.1:18080", "127.0.0.1:18080"),
        )
        for origin, host in cases:
            with self.subTest(origin=origin):
                surface = GatewaySettings().http_for_origin(origin)
                self.assertEqual(surface.allowed_hosts, (host,))
                self.assertEqual(surface.allowed_origins, (origin,))

    def test_reject_insecure_external_or_ambiguous_public_url(self) -> None:
        for origin in (
            "http://node.example",
            "https://node.example/path",
            "https://node.example/evil?x=1",
            "https://user:pass@node.example",
            "https://node.example?redirect=https://attacker.example",
            "https://node.example#fragment",
            "https://*.example",
            "https://node.example:invalid-port",
            "https://node.example,https://attacker.example",
            "https://node.example\n.attacker.example",
            "https://node.example:",
            "",
        ):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                GatewaySettings().http_for_origin(origin)

    def test_independent_env_allowlists_cannot_broaden_canonical_origin(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MCP_ALLOWED_HOSTS": "attacker.example:*,*",
                "MCP_ALLOWED_ORIGINS": "https://attacker.example",
            },
        ):
            surface = GatewaySettings().http_for_origin("https://node.example")
        self.assertEqual(surface.allowed_hosts, ("node.example",))
        self.assertEqual(surface.allowed_origins, ("https://node.example",))

    def test_coolify_generated_url_precedes_deprecated_generic_alias(self) -> None:
        with patch.dict(os.environ, {
            "SERVICE_URL_GATEWAY": "https://canonical.example",
            "MCP_PUBLIC_BASE_URL": "https://stale.example",
        }, clear=True):
            settings = GatewayAuthSettings()
        self.assertEqual(settings.public_base_url, "https://canonical.example")
