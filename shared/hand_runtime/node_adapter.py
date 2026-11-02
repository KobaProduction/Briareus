"""Authenticated SDK composition for independently packaged Node MCP Hands."""

from __future__ import annotations

import hashlib
import inspect
import logging
import os
import time
import traceback
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

import uvicorn
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from fastmcp.tools import Tool, ToolResult
from mcp.types import CallToolRequest, CallToolRequestParams, CallToolResult
from starlette.applications import Starlette
from starlette.types import ASGIApp

from node_protocol import Deployment
from node_protocol.control import canonical
from node_protocol.effect import (
    EffectPermit,
    EffectVerifier,
    HumanEffectPermit,
    NodeEffectPermit,
)
from node_protocol.module_effects import MODULES

from .errors import NodePreparing
from .node_boundary import EffectBoundary
from .node_dispatch_application import DispatchNodeTool
from .node_supervisor_io import require_supervisor_sandbox, supervisor_listener
from .provider_ipc import ProviderContext
from .runtime_policy import runtime_policy
from .tool_binding import bind_delegated_tool

type ExecuteNodeTool = Callable[
    [CallToolRequestParams, NodeEffectPermit], Awaitable[CallToolResult | ToolResult]
]
type ExecuteHumanTool = Callable[
    [CallToolRequestParams, HumanEffectPermit], Awaitable[CallToolResult | ToolResult]
]
type RegisterNodeTools = Callable[[FastMCP[None]], Awaitable[None] | None]
type HandLifespan = Callable[[Starlette], AbstractAsyncContextManager[None]]


def invocation_context() -> ProviderContext:
    request = get_http_request()
    permit = request.scope.get("briareus.node_effect")
    if not isinstance(permit, NodeEffectPermit) or permit.expires_at <= time.time():
        raise ValueError("Current private invocation authority required")
    context = request.scope.get("briareus.invocation_context")
    if not isinstance(context, ProviderContext):
        raise ValueError("Current typed invocation context required")
    return context


@dataclass(frozen=True, slots=True)
class NodeDelegatedTool:
    name: str
    _execute: ExecuteNodeTool
    _module: str
    _human_execute: ExecuteHumanTool | None = None

    def _permit(self, call: CallToolRequest) -> EffectPermit:
        permit = get_http_request().scope.get("briareus.node_effect")
        if (
            not isinstance(permit, (NodeEffectPermit, HumanEffectPermit))
            or permit.module != self._module
            or permit.method != "tools/call"
            or permit.tool != self.name
            or call.params.name != self.name
            or permit.expires_at <= time.time()
            or permit.arguments_digest
            != hashlib.sha256(canonical(call.params.arguments or {})).hexdigest()
        ):
            raise ToolError("CURRENT_NODE_EFFECT_REQUIRED")
        return permit

    async def run(self) -> ToolResult:
        call = get_http_request().scope.get("briareus.node_call")
        if not isinstance(call, CallToolRequest):
            raise ToolError("CURRENT_NODE_EFFECT_REQUIRED")
        permit = self._permit(call)
        logging.getLogger(__name__).info(
            "Node effect admitted module=%s tool=%s", self._module, self.name
        )
        try:

            async def invoke() -> CallToolResult | ToolResult:
                if isinstance(permit, HumanEffectPermit):
                    if self._human_execute is None:
                        raise ToolError("HUMAN_WEB_EXECUTOR_UNAVAILABLE")
                    return await self._human_execute(call.params, permit)
                return await self._execute(call.params, permit)

            dispatch = DispatchNodeTool(
                invoke,
                clock=time.time,
                execution_timeout=lambda: runtime_policy().execution_timeout_seconds,
            )
            result = await dispatch.execute(expires_at=permit.expires_at)
            logging.getLogger(__name__).info(
                "Node effect completed module=%s tool=%s", self._module, self.name
            )
            return result if isinstance(result, ToolResult) else ToolResult.from_mcp_result(result)
        except NodePreparing:
            raise ToolError("NODE_PREPARING") from None
        except Exception as error:
            cause = error.__cause__ or error.__context__ or error
            incident = uuid4().hex
            logging.getLogger(__name__).error(
                "Node effect failed incident=%s module=%s exception=%s frames=%s",
                incident,
                self._module,
                type(cause).__name__,
                tuple(
                    (frame.name, frame.lineno)
                    for frame in traceback.extract_tb(cause.__traceback__)
                ),
            )
            raise ToolError("NODE_EFFECT_REJECTED_OR_UNAVAILABLE incident=" + incident) from None


def _copy_tool(
    original: Tool,
    module: str,
    execute: ExecuteNodeTool,
    human_execute: ExecuteHumanTool | None = None,
) -> Tool:
    runner = NodeDelegatedTool(original.name, execute, module, human_execute)
    return bind_delegated_tool(original, runner.run)


async def _register_catalogue(
    template: FastMCP[None],
    server: FastMCP[None],
    register: RegisterNodeTools,
    spec: Deployment,
    execute: ExecuteNodeTool,
    human_execute: ExecuteHumanTool | None = None,
) -> tuple[str, ...]:
    registration = register(template)
    if inspect.isawaitable(registration):
        await registration
    tools = await template.list_tools()
    names = tuple(item.name for item in tools)
    if not names or len(names) > 512 or len(set(names)) != len(names):
        raise ValueError("A bounded unique original tool catalogue is required")
    for original in tools:
        server.add_tool(_copy_tool(original, spec.release.module, execute, human_execute))
    return names


def _supervisor_lifespan(
    warmup: Callable[[], Awaitable[None]], close: Callable[[], Awaitable[None]]
) -> HandLifespan:
    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        await warmup()
        try:
            yield
        finally:
            await close()

    return lifespan


def create_node_app(
    spec: Deployment,
    *,
    register_tools: RegisterNodeTools,
    execute: ExecuteNodeTool,
    execute_human: ExecuteHumanTool | None = None,
    lifespan: HandLifespan | None = None,
    ready: Callable[[], bool] = lambda: True,
) -> EffectBoundary:
    verifier = EffectVerifier(spec)
    template: FastMCP[None] = FastMCP("node-source-" + spec.release.module)
    mcp: FastMCP[None] = FastMCP("briareus-node-" + spec.release.module)
    app = mcp.http_app(
        path="/mcp",
        stateless_http=True,
        json_response=True,
        host_origin_protection=True,
        allowed_hosts=[
            spec.container_name + "." + spec.release.module,
            spec.container_name + ":" + str(spec.release.port),
            "localhost",
        ],
    )
    sdk_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def application_lifespan(
        current: Starlette,
    ) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            if lifespan is not None:
                await stack.enter_async_context(lifespan(current))
            current.state.node_tool_names = await _register_catalogue(
                template, mcp, register_tools, spec, execute, execute_human
            )
            state = await stack.enter_async_context(sdk_lifespan(current))
            # The pinned SDK HTTP transport lifespan yields None, not application state.
            if state is not None:
                raise ValueError("Unexpected Node HTTP transport lifespan state")
            async with Client(mcp, timeout=120) as metadata:
                await metadata.list_tools()
            yield

    app.router.lifespan_context = application_lifespan
    app.state.node_spec = spec
    return EffectBoundary(
        app, verifier, code=spec.release.module.upper() + "_CURRENT_AUTHORITY_REQUIRED", ready=ready
    )


def run_node_app(create_app: Callable[[Deployment], ASGIApp], module: str) -> None:
    """Fixed Unix ingress for a trusted supervisor in its rootless PID namespace."""
    if module not in MODULES:
        raise ValueError("Approved MCP module required")
    spec = Deployment.model_validate_json(os.environ["BRIAREUS_DEPLOYMENT"])
    if spec.release.module != module:
        raise ValueError("Exact deployment module required")
    require_supervisor_sandbox()
    with supervisor_listener(module) as listener:
        uvicorn.Server(
            uvicorn.Config(
                create_app(spec), access_log=False, proxy_headers=False, timeout_graceful_shutdown=3
            )
        ).run(sockets=[listener])
