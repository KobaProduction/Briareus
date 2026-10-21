"""Bounded Node infrastructure source and account boundary checks."""
import asyncio
import json
import unittest
from infrastructure_hand.dispatch import SourceToolDispatch
from infrastructure_hand.invocation_accounts import InvocationAccounts


class InfrastructureNodeTests(unittest.TestCase):
    def test_original_eighteen_tools_are_reused_without_legacy_runtime(self):
        dispatch = SourceToolDispatch(InvocationAccounts([]))
        self.assertEqual(len(dispatch.tools), 18)
        self.assertIn("observability_application_variables", dispatch.tools)
        self.assertIn("observability_search_logs", dispatch.tools)
        result = asyncio.run(dispatch.call("observability_sources", {}))
        self.assertEqual(result, {"sources": [], "count": 0})
        dispatch.clear()

    def test_public_source_metadata_has_no_credential(self):
        row = {"id": "scope-owned", "alias": "selected", "provider": "coolify",
               "auth_type": "bearer", "base_url": "https://example.com",
               "enabled": True, "created_at": "", "updated_at": ""}
        port = InvocationAccounts([row])
        dispatch = SourceToolDispatch(port)
        result = asyncio.run(dispatch.call("observability_sources", {}))
        self.assertEqual(result["count"], 1)
        self.assertNotIn("credential", json.dumps(result))
        with self.assertRaises(ValueError):
            asyncio.run(dispatch.call("observability_current_team", {"account_id": "selected"}))
        dispatch.clear()
        port.clear()

    def test_secret_and_cross_provider_are_not_in_source_metadata(self):
        port = InvocationAccounts([{"id": "scope-owned", "alias": "selected", "provider": "signoz",
            "auth_type": "api_key", "base_url": "https://example.com", "enabled": True,
            "created_at": "", "updated_at": "", "credential": "fixture-private-key"}])
        self.assertNotIn("fixture-private-key", json.dumps(port.list_accounts().to_json()))
        with self.assertRaises(ValueError):
            port.resolve_account("selected", provider="coolify")
        with self.assertRaises(ValueError):
            port.resolve_account("not-granted", provider="signoz")
