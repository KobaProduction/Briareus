"""Common local-first policy enforcement for source-control MCP providers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

import mcp.types as mt
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import Tool, ToolResult


class WorkflowPolicy(Protocol):
    @property
    def local_first_guidance(self) -> bool: ...
    @property
    def local_git_transport_enabled(self) -> bool: ...
    @property
    def remote_source_mutations_enabled(self) -> bool: ...


@dataclass(frozen=True)
class WorkflowConfig:
    provider: str
    source_mutations: frozenset[str]
    local_git_tools: frozenset[str]
    guidance_tools: frozenset[str]
    guidance: str
    remote_denial: str
    local_denial: str
    checkout_description: str
    checkout_guidance: str
    report_local_transport: bool = True


class LocalFirstMiddleware(Middleware):
    """Provider-neutral enforcement with owner-defined tool groups and messages."""

    def __init__(
        self, policy_provider: Callable[[], WorkflowPolicy], config: WorkflowConfig
    ) -> None:
        self.policy_provider = policy_provider
        self.config = config

    def _denial(self, name: str, policy: WorkflowPolicy) -> str:
        if name in self.config.source_mutations and not policy.remote_source_mutations_enabled:
            return self.config.remote_denial
        if name in self.config.local_git_tools and not policy.local_git_transport_enabled:
            return self.config.local_denial
        return ""

    def _description_prefix(self, name: str, policy: WorkflowPolicy) -> str:
        denial = self._denial(name, policy)
        if denial:
            return denial + " "
        if not policy.local_first_guidance:
            return ""
        if name == "checkout_repository":
            return self.config.checkout_description + " "
        if name in self.config.source_mutations:
            return self.config.guidance + " "
        return ""

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        policy = self.policy_provider()
        adapted: list[Tool] = []
        for tool in tools:
            prefix = self._description_prefix(tool.name, policy)
            adapted.append(
                tool.model_copy(update={"description": prefix + (tool.description or "")})
                if prefix
                else tool
            )
        return adapted

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        name = context.message.name
        policy = self.policy_provider()
        denial = self._denial(name, policy)
        if denial:
            raise ToolError(denial)
        result = await call_next(context)
        if not policy.local_first_guidance or name not in self.config.guidance_tools:
            return result
        guidance = (
            self.config.checkout_guidance if name == "checkout_repository" else self.config.guidance
        )
        content = [*result.content, mt.TextContent(type="text", text=guidance)]
        meta = dict(result.meta or {})
        policy_meta = {
            "local_first_guidance": True,
            "remote_source_mutations_enabled": policy.remote_source_mutations_enabled,
        }
        if self.config.report_local_transport:
            policy_meta["local_git_transport_enabled"] = policy.local_git_transport_enabled
        meta[f"koba/{self.config.provider}-workflow"] = policy_meta
        return result.model_copy(update={"content": content, "meta": meta})
