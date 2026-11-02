"""Compatibility exports for the shared provider implementation."""

import json as json

from fastmcp.tools import ToolResult as ToolResult
from mcp.types import CallToolResult as CallToolResult
from mcp.types import TextContent as TextContent

from common.http_transport import HttpTransportResponse as HttpTransportResponse
from infrastructure_runtime.providers.signoz.presentation.results import (
    signoz_result as signoz_result,
)
