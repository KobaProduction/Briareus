from __future__ import annotations

import importlib
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from unittest.mock import patch

from briareus_account_contracts import AccountList, AccountPublic, ResolvedAccount
from briareus_control_panel_client.control_panel_client import ControlPanelClient
from briareus_hand_runtime import ProviderClientCache
from fastmcp import Client, FastMCP


def account(revision: str = "revision-1") -> ResolvedAccount:
    return ResolvedAccount(
        id="source-id",
        alias="telemetry",
        provider="signoz",
        auth_type="api_key",
        base_url="https://telemetry.example.test",
        credential="test-private-credential",
        created_at="created",
        updated_at=revision,
    )


@dataclass(frozen=True)
class ProviderClient:
    account: ResolvedAccount


class ProviderAccountCacheContracts(unittest.TestCase):
    def test_listing_is_provider_scoped_and_never_serializes_credentials(self) -> None:
        management = object.__new__(ControlPanelClient)
        public = AccountPublic.model_validate(account().model_dump(exclude={"credential"}))
        with patch.object(
            ControlPanelClient,
            "list_accounts",
            return_value=AccountList(accounts=[public], count=1),
        ) as listing:
            cache = ProviderClientCache(management, "signoz", ProviderClient)
            sources = cache.sources()
        listing.assert_called_once_with(provider="signoz")
        self.assertEqual(sources.count, 1)
        self.assertEqual(sources.sources[0].provider, "signoz")
        self.assertNotIn("credential", sources.model_dump_json())

    def test_concurrent_reads_reuse_one_client_and_rotation_replaces_it(self) -> None:
        management = object.__new__(ControlPanelClient)
        cache = ProviderClientCache(management, "signoz", ProviderClient)
        with patch.object(ControlPanelClient, "resolve_account", return_value=account()) as resolve:
            with ThreadPoolExecutor(max_workers=8) as pool:
                clients = list(pool.map(cache.client, ["telemetry"] * 16))
            self.assertTrue(all(client is clients[0] for client in clients))
            resolve.assert_called_with("telemetry", provider="signoz")
            resolve.return_value = account("revision-2")
            replacement = cache.client("telemetry")
        self.assertIsNot(replacement, clients[0])
        self.assertEqual(replacement.account.updated_at, "revision-2")


def private_server(
    name: str,
    management: ControlPanelClient | None = None,
    *,
    observability_scope: str | None = None,
) -> FastMCP[None]:
    del management, observability_scope
    return FastMCP(name)


class ProviderMcpIsolationContracts(unittest.IsolatedAsyncioTestCase):
    async def test_sig_noz_and_coolify_publish_independent_catalogs(self) -> None:
        management = object.__new__(ControlPanelClient)
        with (
            patch(
                "briareus_hand_runtime.runtime_common.management_client", return_value=management
            ),
            patch(
                "briareus_hand_runtime.runtime_common.build_private_mcp",
                side_effect=private_server,
            ),
        ):
            signoz = importlib.import_module("briareus_signoz.runtime")
            coolify = importlib.import_module("briareus_coolify.runtime")
        async with Client(signoz.mcp) as client:
            signoz_tools = await client.list_tools()
        async with Client(coolify.mcp) as client:
            coolify_tools = await client.list_tools()
        self.assertEqual(len(signoz_tools), 8)
        self.assertEqual(len(coolify_tools), 12)
        self.assertTrue(all(tool.name.startswith("signoz_") for tool in signoz_tools))
        self.assertTrue(all(tool.name.startswith("coolify_") for tool in coolify_tools))
        self.assertTrue(
            all(
                tool.annotations and tool.annotations.read_only_hint
                for tool in [*signoz_tools, *coolify_tools]
            )
        )
        self.assertFalse(
            any("observability_" in tool.name for tool in [*signoz_tools, *coolify_tools])
        )
