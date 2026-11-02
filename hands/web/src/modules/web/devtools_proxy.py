"""Compatibility API for the bounded internal CDP target adapter."""

from __future__ import annotations

import contextlib as contextlib
import logging as logging
import os as os
import re as re
import threading as threading
from collections.abc import Awaitable as Awaitable
from collections.abc import Callable as Callable
from collections.abc import Sequence as Sequence
from pathlib import Path as Path
from typing import TextIO as TextIO
from typing import cast as cast

import mcp.types as mt
from fastmcp import FastMCP as FastMCP
from fastmcp.client.transports import StdioTransport as StdioTransport
from fastmcp.exceptions import ToolError as ToolError
from fastmcp.server.middleware import CallNext as CallNext
from fastmcp.server.middleware import Middleware as Middleware
from fastmcp.server.middleware import MiddlewareContext as MiddlewareContext
from fastmcp.server.providers.proxy import FastMCPProxy as FastMCPProxy
from fastmcp.server.providers.proxy import ProxyClient as ProxyClient
from fastmcp.tools import Tool as Tool
from fastmcp.tools import ToolResult as ToolResult

from common.settings import BrowserSettings as BrowserSettings
from web_runtime.infrastructure.proxy import browser_proxy as browser_proxy
from web_runtime.targets.devtools import _SECRET_ASSIGNMENT_RE as _SECRET_ASSIGNMENT_RE
from web_runtime.targets.devtools import CHROME_DEVTOOLS_MCP_VERSION as CHROME_DEVTOOLS_MCP_VERSION
from web_runtime.targets.devtools import DeveloperAccessMiddleware as DeveloperAccessMiddleware
from web_runtime.targets.devtools import DevToolsProxyRuntime as _DevToolsProxyRuntime
from web_runtime.targets.devtools import _DevToolsStderrForwarder as _DevToolsStderrForwarder
from web_runtime.targets.devtools import _redact_upstream_stderr as _redact_upstream_stderr
from web_runtime.targets.devtools import logger as logger

from .browser import BrowserError as BrowserError
from .browser import BrowserManager as BrowserManager

__all__ = [
    "CHROME_DEVTOOLS_MCP_VERSION",
    "_SECRET_ASSIGNMENT_RE",
    "Awaitable",
    "BrowserError",
    "BrowserManager",
    "BrowserSettings",
    "CallNext",
    "Callable",
    "DevToolsProxyRuntime",
    "DeveloperAccessMiddleware",
    "FastMCP",
    "FastMCPProxy",
    "Middleware",
    "MiddlewareContext",
    "Path",
    "ProxyClient",
    "Sequence",
    "StdioTransport",
    "TextIO",
    "Tool",
    "ToolError",
    "ToolResult",
    "_DevToolsStderrForwarder",
    "_redact_upstream_stderr",
    "browser_proxy",
    "cast",
    "contextlib",
    "logger",
    "logging",
    "mt",
    "os",
    "re",
    "threading",
]


class DevToolsProxyRuntime[AppState](_DevToolsProxyRuntime[AppState]):
    def __init__(
        self,
        browser: BrowserManager,
        settings: BrowserSettings,
        *,
        workspace: Path = Path("/workspace"),
    ) -> None:
        super().__init__(browser, settings, workspace=workspace)
