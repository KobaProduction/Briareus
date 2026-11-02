"""Compatibility exports for the shared Analysis client implementation."""

from __future__ import annotations

import json as json

from fastmcp.tools import ToolResult as ToolResult
from mcp.types import CallToolResult as CallToolResult
from mcp.types import TextContent as TextContent

from project_runtime_client.analysis.result import _public_text as _public_text
from project_runtime_client.analysis.result import adapt_analysis_result as adapt_analysis_result
from project_runtime_client.analysis.result import decode_call_result as decode_call_result

from .terminology import analysis_group_name as analysis_group_name
from .terminology import analysis_result_key as analysis_result_key
from .terminology import analysis_result_text as analysis_result_text
from .terminology import analysis_text as analysis_text
from .terminology import analysis_tool_name as analysis_tool_name
