"""Compatibility API for the bounded external Playwright target adapter."""

from __future__ import annotations

import asyncio as asyncio
import logging as logging
from collections.abc import AsyncIterator as AsyncIterator
from collections.abc import Awaitable as Awaitable
from collections.abc import Callable as Callable
from contextlib import asynccontextmanager as asynccontextmanager
from contextlib import suppress as suppress
from datetime import UTC as UTC
from datetime import datetime as datetime
from types import TracebackType as TracebackType
from urllib.parse import urlsplit as urlsplit

from fastmcp import FastMCP as FastMCP
from fastmcp.client.client import CallToolResult as CallToolResult
from fastmcp.client.transports import StreamableHttpTransport as StreamableHttpTransport
from fastmcp.server.providers.proxy import FastMCPProxy as FastMCPProxy
from fastmcp.server.providers.proxy import ProxyClient as ProxyClient
from mcp.types import CallToolRequestParams as CallToolRequestParams

from common.runtime_policy_contracts import BrowserRuntimePolicy as BrowserRuntimePolicy
from service_runtime.mcp_http import mcp_http_client as mcp_http_client
from web_runtime.infrastructure.proxy import browser_proxy as browser_proxy
from web_runtime.targets.external import ExternalBrowserProxyRuntime as _ExternalBrowserProxyRuntime
from web_runtime.targets.external import PolicyProvider as PolicyProvider
from web_runtime.targets.external import (
    _PersistentPlaywrightProxyClient as _PersistentPlaywrightProxyClient,
)
from web_runtime.targets.external import logger as logger

from .domain.external_tabs import require_tab_capacity as require_tab_capacity
from .external_browser_models import ExternalBrowserStatus as ExternalBrowserStatus


class ExternalBrowserProxyRuntime[AppState](_ExternalBrowserProxyRuntime[AppState]):
    async def guarded_call(self, call: CallToolRequestParams) -> CallToolResult:
        """Bound known upstream tab creation without taking over user tabs."""
        from hand_runtime.runtime_policy import runtime_policy

        limits = runtime_policy()
        client = await self._ensure_client()
        lease = await client.acquire()
        async with lease:
            if call.name == "browser_tabs" and (call.arguments or {}).get("action") == "new":
                if limits.web_tab_idle_seconds is not None:
                    raise RuntimeError(
                        "EXTERNAL_TAB_CREATION_UNSUPPORTED_IDLE_OWNERSHIP: "
                        "use local browser for automatically managed tabs"
                    )
                if limits.web_max_tabs is not None:
                    inventory = await lease.call_tool(
                        "browser_tabs", {"action": "list"}, raise_on_error=False
                    )
                    if inventory.is_error:
                        raise RuntimeError("External tab inventory unavailable")
                    text = "\n".join(getattr(item, "text", "") for item in inventory.content)
                    # Official Playwright returns numbered tab lines. Unknown
                    # formats cannot silently bypass a configured capacity.
                    require_tab_capacity(text, limits.web_max_tabs)
            return await lease.call_tool(call.name, call.arguments or {}, raise_on_error=False)
