from __future__ import annotations

import asyncio
import unittest
from types import TracebackType
from typing import cast
from unittest.mock import patch

from briareus_browser_policy import BrowserRuntimePolicy
from briareus_playwright.external import (
    ExternalBrowserProxyRuntime,
    _PersistentPlaywrightProxyClient,
)
from fastmcp import FastMCP


class ToolResult:
    def __init__(self, is_error: bool = False) -> None:
        self.is_error = is_error


class ExternalEndpoint:
    def __init__(self, *, failure: str = "", error_result: bool = False) -> None:
        self.policy = BrowserRuntimePolicy()
        self.failure = failure
        self.error_result = error_result
        self.connected = True
        self.connect_count = 1
        self.last_activity_at = ""
        self.acquires = 0
        self.probes = 0
        self.shutdowns = 0
        self.pending: asyncio.Event | None = None

    async def acquire(self) -> ExternalEndpoint:
        self.acquires += 1
        if self.failure == "initialize":
            raise TimeoutError("PRIVATE-SESSION-CREDENTIAL")
        return self

    async def __aenter__(self) -> ExternalEndpoint:
        return self

    async def __aexit__(
        self,
        _kind: type[BaseException] | None,
        _error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        return None

    async def list_tools(self) -> list[str]:
        if self.failure == "catalog":
            raise ConnectionError("PRIVATE-UPSTREAM-HEADER")
        return ["browser_tabs"]

    async def call_tool(self, name: str, arguments: object, **_options: object) -> ToolResult:
        if name != "browser_tabs" or arguments != {"action": "list"}:
            raise AssertionError("Unexpected upstream operation")
        self.probes += 1
        if self.pending is not None:
            await self.pending.wait()
        if self.failure == "tabs":
            raise TimeoutError("PRIVATE-REMOTE-URL")
        return ToolResult(self.error_result)

    async def shutdown(self) -> None:
        self.shutdowns += 1


class ExternalBrowserEndpointContracts(unittest.IsolatedAsyncioTestCase):
    def runtime(self, endpoint: ExternalEndpoint | None = None) -> ExternalBrowserProxyRuntime:
        policy = BrowserRuntimePolicy(
            external_enabled=True, external_mcp_url="http://endpoint.test/mcp"
        )

        async def current_policy() -> BrowserRuntimePolicy:
            return policy

        runtime = ExternalBrowserProxyRuntime(current_policy)
        if endpoint is not None:
            endpoint.policy = policy
            runtime._client = cast(_PersistentPlaywrightProxyClient, endpoint)
            runtime._client_policy = policy
        return runtime

    async def test_catalog_discovery_and_status_never_create_an_external_session(self) -> None:
        runtime = self.runtime()
        catalog = FastMCP("Briareus browser")
        catalog.mount(runtime.server, namespace="external")
        with (
            patch(
                "briareus_playwright.external._PersistentPlaywrightProxyClient",
                side_effect=AssertionError("Discovery must not connect an external endpoint"),
            ),
            self.assertNoLogs("fastmcp.server.providers.aggregate", level="WARNING"),
        ):
            self.assertEqual(list(await catalog.list_tools()), [])
            self.assertEqual(list(await catalog.list_resources()), [])
            self.assertEqual(list(await catalog.list_prompts()), [])
            status = await runtime.status()
        self.assertFalse(status["connected"])
        self.assertIsNone(status["browser_ready"])
        self.assertEqual(status["grant_state"], "unverified")

    async def test_successful_probe_is_readiness_evidence_not_an_operational_grant(self) -> None:
        endpoint = ExternalEndpoint()
        runtime = self.runtime(endpoint)
        await runtime.connect()
        assert runtime._connect_task is not None
        await runtime._connect_task
        status = await runtime.status()
        self.assertTrue(status["browser_ready"])
        self.assertEqual(status["grant_state"], "unverified")
        self.assertEqual(status["other_client_sessions"], "not_observable")
        await runtime.connect()
        self.assertEqual(endpoint.probes, 1)
        await runtime.disconnect()

    async def test_pending_probe_is_not_duplicated_and_disconnect_cancels_it(self) -> None:
        endpoint = ExternalEndpoint()
        endpoint.pending = asyncio.Event()
        runtime = self.runtime(endpoint)
        first = await runtime.connect()
        await asyncio.sleep(0)
        second = await runtime.connect()
        self.assertTrue(first["connecting"])
        self.assertTrue(second["connecting"])
        self.assertEqual(endpoint.probes, 1)
        await runtime.disconnect()
        self.assertEqual(endpoint.shutdowns, 1)
        self.assertIsNone(runtime._connect_task)

    async def test_diagnostics_identify_failed_stage_without_leaking_private_values(self) -> None:
        for failure, stage in (
            ("initialize", "mcp_initialize"),
            ("catalog", "tools_list"),
            ("tabs", "tabs_list"),
        ):
            with self.subTest(stage=stage):
                runtime = self.runtime(ExternalEndpoint(failure=failure))
                await runtime.connect()
                assert runtime._connect_task is not None
                await runtime._connect_task
                status = await runtime.status()
                error = status["last_error"]
                assert isinstance(error, dict)
                self.assertEqual(error["stage"], stage)
                self.assertNotIn("PRIVATE", str(status))
                self.assertEqual(status["grant_state"], "unverified")
                await runtime.disconnect()

    async def test_error_tool_result_is_not_reported_as_browser_ready(self) -> None:
        runtime = self.runtime(ExternalEndpoint(error_result=True))
        await runtime.connect()
        assert runtime._connect_task is not None
        await runtime._connect_task
        status = await runtime.status()
        self.assertEqual(status["connection_state"], "tab_check_failed")
        self.assertEqual(status["grant_state"], "unverified")
        await runtime.disconnect()
