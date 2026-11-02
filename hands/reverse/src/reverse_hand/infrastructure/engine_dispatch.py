"""Adapt the original MCP SDK metadata and results only at the private engine boundary."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from fastmcp.client.client import CallToolResult as ClientToolResult
from fastmcp.tools import Tool
from mcp.types import CallToolResult, TextContent
from radare2_hand.domain.commands import NativeDeadline as NativeDeadline

from reverse_hand.application.dispatch import DispatchAnalysis, RejectedResult, _DispatchBinding
from reverse_hand.domain.dispatch import AnalysisRequest, Engine, EngineCatalogue, EngineCommand
from reverse_hand.infrastructure.analysis_requests import (
    CurrentAnalysisCall,
    EngineInvocation,
    engine_invocation,
)


class EngineClient(Protocol):
    async def call_tool(
        self, name: str, arguments: dict[str, object], *, raise_on_error: bool
    ) -> ClientToolResult: ...


class McpEngineExecution:
    def __init__(
        self,
        clients: Mapping[Engine, EngineClient],
        deadline: NativeDeadline,
        tools: Mapping[Engine, Sequence[Tool]],
        invocation: EngineInvocation | None = None,
    ) -> None:
        self._clients = clients
        self._deadline = deadline
        self._tools = tools
        self._invocation = invocation

    def bind(self, invocation: EngineInvocation) -> "McpEngineExecution":
        return McpEngineExecution(self._clients, self._deadline, self._tools, invocation)

    def catalogue(self, engine: Engine) -> CallToolResult:
        tools = self._tools[engine]
        text = f"Actual {engine} catalogue: {len(tools)} tools; schemas in structuredContent"
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content={
                "engine": engine,
                "tools": [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": tool.parameters,
                        "outputSchema": tool.output_schema,
                        "annotations": tool.annotations.model_dump(mode="json")
                        if tool.annotations
                        else None,
                    }
                    for tool in tools
                ],
            },
            is_error=False,
        )

    async def invoke(self, command: EngineCommand, deadline: int | None) -> CallToolResult:
        invocation = self._invocation
        if invocation is None or invocation.call is None or invocation.command != command:
            raise ValueError("Actual engine tool required")
        self._deadline.expires_at = deadline
        value = await self._clients[command.engine].call_tool(
            invocation.call.name, invocation.call.arguments or {}, raise_on_error=False
        )
        return CallToolResult(
            content=value.content,
            structured_content=value.structured_content,
            is_error=value.is_error,
            meta=value.meta,
        )


def engine_catalogue(engine: Engine, tools: Sequence[Tool]) -> EngineCatalogue:
    return EngineCatalogue(engine, frozenset(tool.name for tool in tools))


class AnalysisIngress(_DispatchBinding[McpEngineExecution]):
    """Validate SDK arguments once and bind them to this request's execution port."""

    async def execute(self, current: CurrentAnalysisCall) -> CallToolResult | RejectedResult:
        try:
            invocation = engine_invocation(current.call)
        except (ValueError, TypeError, KeyError):
            return RejectedResult("REVERSE_OPERATION_REJECTED_OR_UNAVAILABLE")
        request = AnalysisRequest(
            current.request_uuid,
            invocation.command,
            current.expires_at,
            long_operation=current.call.name == "analysis_start",
        )
        use_case = DispatchAnalysis(
            self._catalogues,
            self._execution.bind(invocation),
            self._now,
            self._long_timeout,
        )
        return await use_case.execute(request)
