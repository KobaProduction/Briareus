"""Serialize mutation receipts at the existing MCP boundary without a result wrapper."""

from collections.abc import Callable

from mcp.types import CallToolResult

from service_runtime.mcp_dataclass_results import dataclass_result

from .application.mutations import AtomicResult, CopyResult

mutation_result: Callable[[AtomicResult | CopyResult], CallToolResult] = dataclass_result
