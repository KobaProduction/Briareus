from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastmcp.client.client import CallToolResult as ClientCallToolResult
from mcp.types import CallToolRequestParams, TextContent, Tool

from bridge.application.backend_routing import BackendLocation, BackendRouting
from bridge.backend_router import BackendRouter
from bridge.domain.backend_failure import tool_failure
from bridge.infrastructure.backend_routing import BackendDescriptor
from bridge.presentation.backend_models import BackendCallFailure, BackendView
from bridge.presentation.backend_results import catalog_reply


class BackendStub:
    def __init__(self) -> None:
        self.catalog_requests: list[str] = []

    async def tool_count(self, name: str) -> int:
        self.catalog_requests.append(name)
        if name == "offline":
            raise ConnectionError("private upstream URL")
        return 1


class BackendRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.port = BackendStub()
        self.routing = BackendRouting(
            (
                BackendLocation("online", "/online", "Available"),
                BackendLocation("offline", "/offline", "Unavailable"),
            ),
            self.port,
        )
        self.router = BackendRouter(
            (
                BackendDescriptor[None](
                    "online", "https://fixture.invalid/mcp", "/online", "Available"
                ),
            )
        )

    async def asyncTearDown(self) -> None:
        await self.router.close()

    async def test_directory_keeps_order_and_isolates_failed_probe(self) -> None:
        result = await self.routing.describe()
        self.assertEqual(tuple(item.location.name for item in result), ("online", "offline"))
        self.assertEqual(result[0].status, "available")
        self.assertEqual(result[0].tool_count, 1)
        self.assertEqual(result[1].status, "not_available")
        self.assertEqual(result[1].error_type, "ConnectionError")
        self.assertEqual(self.port.catalog_requests, ["online", "offline"])

    async def test_uncertain_write_is_redacted_and_never_retried(self) -> None:
        request = CallToolRequestParams(name="write", arguments={"value": 1})
        invoke = AsyncMock(side_effect=TimeoutError("private upstream credentials"))
        with patch.object(self.router._gateway, "invoke", invoke):
            outcome = await self.router.call(" ONLINE ", request)
        invoke.assert_awaited_once_with("online", request)
        failure = BackendCallFailure.model_validate(outcome.structured_content)
        self.assertEqual(failure.error_type, "MCP_BACKEND_TIMEOUT")
        self.assertNotIn("private", failure.message)
        self.assertIn("unknown", failure.hint)

    async def test_reported_tool_error_remains_failure(self) -> None:
        request = CallToolRequestParams(name="inspect")
        result = ClientCallToolResult(
            content=[TextContent(type="text", text="private upstream error")],
            structured_content=None,
            meta=None,
            is_error=True,
        )
        invoke = AsyncMock(return_value=result)
        with patch.object(self.router._gateway, "invoke", invoke):
            outcome = await self.router.call("online", request)
        invoke.assert_awaited_once_with("online", request)
        failure = BackendCallFailure.model_validate(outcome.structured_content)
        expected = tool_failure()
        self.assertEqual(failure.error_type, expected.error_type)
        self.assertEqual(failure.message, expected.message)
        self.assertNotIn("private upstream", str(outcome.structured_content))

    async def test_unknown_backend_is_rejected_before_transport(self) -> None:
        invoke = AsyncMock()
        with patch.object(self.router._gateway, "invoke", invoke), self.assertRaises(ValueError):
            await self.router.call("other", CallToolRequestParams(name="write"))
        invoke.assert_not_awaited()

    async def test_wire_optional_fields_remain_absent(self) -> None:
        result = BackendView(
            name="online",
            public_path="/online",
            purpose="Available",
            status="available",
            tool_count=1,
        )
        self.assertNotIn("error_type", result.model_dump(mode="json"))
        catalogue = catalog_reply(
            BackendLocation("online", "/online", "Available"),
            (Tool(name="inspect", description="Read metadata", input_schema={"type": "object"}),),
        )
        self.assertEqual(
            catalogue.structured_content,
            {
                "backend": "online",
                "public_path": "/online",
                "status": "available",
                "tools": [
                    {
                        "name": "inspect",
                        "description": "Read metadata",
                        "input_schema": {"type": "object"},
                    }
                ],
                "count": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
