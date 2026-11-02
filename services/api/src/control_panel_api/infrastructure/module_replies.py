"""Concrete adapter bindings for owned receipts and external MCP SDK results."""

from mcp_types import CallToolResult

from control_panel_api.application.module_contracts import HumanModuleReply

type NativeToolReply = CallToolResult
type NativeModuleReply = HumanModuleReply[NativeToolReply]
