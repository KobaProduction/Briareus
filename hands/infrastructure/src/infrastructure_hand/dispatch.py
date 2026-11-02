"""Typed private dispatch of original provider callables; no second MCP server."""

from collections.abc import Awaitable
from collections.abc import Callable as Callable
from inspect import isawaitable

from mcp.types import CallToolRequestParams, CallToolResult, ToolAnnotations
from pydantic import BaseModel
from pydantic.json_schema import JsonSchemaValue as JsonSchemaValue

from hand_runtime.account_lease import InvocationAccounts
from hand_runtime.provider_results import provider_result
from hand_runtime.tool_binding import ValidatedInvocation, _SourceToolRegistration
from hand_runtime.tool_binding import bind_invocation as bind_invocation
from node_protocol.provider_context import InvocationPolicies

from .source_tools import register_source_tools


class SourceToolDispatch(_SourceToolRegistration):
    def __init__(
        self, accounts: InvocationAccounts, policies: InvocationPolicies | None = None
    ) -> None:
        self.tools: dict[str, ValidatedInvocation[BaseModel | Awaitable[BaseModel]]] = {}
        self.annotations: dict[str, ToolAnnotations | None] = {}
        self.contexts = register_source_tools(self, accounts, policies)
        self._context_clearers = tuple(context.clear for context in self.contexts)

    def configure(self, policies: InvocationPolicies | None) -> None:
        del policies

    async def call(self, call: CallToolRequestParams) -> CallToolResult:
        name = call.name
        if name not in self.tools:
            raise ValueError("Unregistered provider tool")
        result = self.tools[name](call)
        outcome = await result if isawaitable(result) else result
        wire = provider_result(outcome)
        structured = wire.structured_content
        if structured is not None and not isinstance(structured, dict):
            raise ValueError("Provider structured content must be an object")
        return wire
