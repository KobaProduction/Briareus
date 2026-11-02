"""Deny broad grants/audiences or browser redirects on the server-only broker."""

import json
import unittest
from dataclasses import asdict

from resource_broker_contract import CLIENT_ID, configuration, verify_configuration


class BrokerContractTests(unittest.TestCase):
    def test_strict_reusable_configuration_and_broad_client_rejected(self) -> None:
        origin = "https://127.0.0.1"
        wanted = {"id": CLIENT_ID, **json.loads(json.dumps(asdict(configuration(origin))))}
        verify_configuration(wanted, origin)
        changesets: list[dict[str, object]] = [
            {"id": "other"},
            {"confidential": False},
            {"flows_enabled": ["client_credentials"]},
            {"allowed_resources": ["https://foreign.invalid/mcp"]},
            {"default_aud": ["admin"]},
            {"redirect_uris": [origin + "/panel/"]},
            {"access_token_lifetime": 86400},
        ]
        for changes in changesets:
            with self.assertRaises(ValueError):
                verify_configuration({**wanted, **changes}, origin)
        with self.assertRaises(ValueError):
            configuration("https://foreign.invalid")

    def test_provider_normalization_preserves_exact_audiences_and_null_fields(self) -> None:
        origin = "https://briareus.koba-nexus.ru"
        wanted = {"id": CLIENT_ID, **json.loads(json.dumps(asdict(configuration(origin))))}
        wanted["allowed_resources"].reverse()
        wanted["scopes"].reverse()
        wanted["default_aud"] = []
        wanted["allowed_origins"] = []
        verify_configuration(wanted, origin)
        wanted["allowed_resources"].append(wanted["allowed_resources"][0])
        with self.assertRaises(ValueError):
            verify_configuration(wanted, origin)
