"""GitLab tool listing adaptation; each local middleware owns its policy hooks."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import mcp.types as mt
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import Tool

from service_runtime.runtime_policy_contracts import GitLabRuntimePolicy
from source_control.providers._policy_binding import _PolicyProviderBinding


class GitLabToolDescriptions(_PolicyProviderBinding[GitLabRuntimePolicy], Middleware):
    _description_prefix: Callable[[str, GitLabRuntimePolicy], str]

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
                tool
                if not prefix
                else tool.model_copy(update={"description": prefix + (tool.description or "")})
            )
        return adapted
