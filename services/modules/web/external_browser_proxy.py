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
from fastmcp.client.transports import StreamableHttpTransport as StreamableHttpTransport
from fastmcp.server.providers.proxy import FastMCPProxy as FastMCPProxy
from fastmcp.server.providers.proxy import ProxyClient as ProxyClient

from common.runtime_policy_contracts import BrowserRuntimePolicy as BrowserRuntimePolicy
from service_runtime.mcp_http import mcp_http_client as mcp_http_client
from web_runtime.infrastructure.proxy import browser_proxy as browser_proxy
from web_runtime.targets.external import ExternalBrowserProxyRuntime as ExternalBrowserProxyRuntime
from web_runtime.targets.external import PolicyProvider as PolicyProvider
from web_runtime.targets.external import (
    _PersistentPlaywrightProxyClient as _PersistentPlaywrightProxyClient,
)
from web_runtime.targets.external import logger as logger

from .external_browser_models import ExternalBrowserStatus as ExternalBrowserStatus
