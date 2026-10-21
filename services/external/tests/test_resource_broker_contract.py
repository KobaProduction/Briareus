"""Deny broad grants/audiences or browser redirects on the server-only broker."""
import unittest
from resource_broker_contract import CLIENT_ID,configuration,verify_configuration


class BrokerContractTests(unittest.TestCase):
    def test_strict_reusable_configuration_and_broad_client_rejected(self):
        origin="https://127.0.0.1"
        wanted={"id":CLIENT_ID,**configuration(origin)}
        verify_configuration(wanted,origin)
        for changes in [{"id":"other"},{"confidential":False},{"flows_enabled":["client_credentials"]},
            {"allowed_resources":["https://foreign.invalid/mcp"]},{"default_aud":["admin"]},
            {"redirect_uris":[origin+"/panel/"]},{"access_token_lifetime":86400}]:
            with self.assertRaises(ValueError):verify_configuration({**wanted,**changes},origin)
        with self.assertRaises(ValueError):configuration("https://foreign.invalid")
