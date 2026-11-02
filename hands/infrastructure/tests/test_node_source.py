"""Bounded Node infrastructure source and account boundary checks."""
import unittest
from typing import Literal
from uuid import uuid4

from mcp.types import CallToolRequestParams

from common.account_contracts import SourceInventoryView
from infrastructure_hand.dispatch import SourceToolDispatch
from infrastructure_hand.invocation_accounts import InvocationAccounts
from node_protocol.provider_context import ProjectAccount


class InfrastructureNodeTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def account(
        provider: Literal["coolify", "signoz"], credential: str | None = None,
    ) -> ProjectAccount:
        account = ProjectAccount(
            id=uuid4(), alias="selected", provider=provider,
            auth_type="bearer" if provider == "coolify" else "api_key",
            base_url="https://example.com", external_id=None, ca_cert_pem=None,
            enabled=True, created_at="", updated_at="",
        )
        if credential is not None:
            return account.model_copy(update={"credential": credential})
        return account

    async def sources(self, dispatch: SourceToolDispatch) -> SourceInventoryView:
        result = await dispatch.call(CallToolRequestParams(
            name="observability_sources", arguments={},
        ))
        self.assertFalse(result.is_error)
        self.assertNotIn("credential", result.model_dump_json())
        return SourceInventoryView.model_validate(result.structured_content)

    async def test_original_eighteen_tools_are_reused_without_legacy_runtime(self) -> None:
        dispatch = SourceToolDispatch(InvocationAccounts([]))
        try:
            self.assertEqual(len(dispatch.tools), 18)
            self.assertIn("observability_application_variables", dispatch.tools)
            self.assertIn("observability_search_logs", dispatch.tools)
            result = await self.sources(dispatch)
            self.assertEqual(result.sources, [])
            self.assertEqual(result.count, 0)
        finally:
            dispatch.clear()

    async def test_public_source_metadata_has_no_credential(self) -> None:
        port = InvocationAccounts([self.account("coolify")])
        dispatch = SourceToolDispatch(port)
        try:
            result = await self.sources(dispatch)
            self.assertEqual(result.count, 1)
            self.assertEqual(result.sources[0].alias, "selected")
            with self.assertRaises(ValueError):
                await dispatch.call(CallToolRequestParams(
                    name="observability_current_team", arguments={"account_id": "selected"},
                ))
        finally:
            dispatch.clear()
            port.clear()

    def test_secret_and_cross_provider_are_not_in_source_metadata(self) -> None:
        port = InvocationAccounts([self.account("signoz", "fixture-private-key")])
        try:
            self.assertNotIn("fixture-private-key", port.list_accounts().model_dump_json())
            with self.assertRaises(ValueError):
                port.resolve_account("selected", provider="coolify")
            with self.assertRaises(ValueError):
                port.resolve_account("not-granted", provider="signoz")
        finally:
            port.clear()
