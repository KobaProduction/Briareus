"""Node Web MCP metadata wrapper; effects execute only in the private child."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager, suppress

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from mcp.types import CallToolRequestParams, CallToolResult
from mcp.types import Tool as ToolMetadata
from starlette.applications import Starlette
from starlette.types import ASGIApp

from common.runtime_policy_contracts import BrowserRuntimePolicy
from hand_runtime.errors import NodePreparing
from hand_runtime.node_adapter import create_node_app, run_node_app
from node_protocol import Deployment
from node_protocol.control_auth import CoreVerifier
from node_protocol.effect import EffectPermit
from node_protocol.models import BrowserConfiguration

from .node_supervisor import WebSupervisor, require_supervisor_isolation
from .operations import register_operations
from .presentation.agent_observation import BrowserObservationBoundary


def _browser_policy(configuration: BrowserConfiguration | None) -> BrowserRuntimePolicy:
    if configuration is None:
        return BrowserRuntimePolicy()
    return BrowserRuntimePolicy(
        external_enabled=configuration.external_enabled,
        external_mcp_url=configuration.external_mcp_url,
        call_timeout_seconds=configuration.call_timeout_seconds,
        auto_disconnect_enabled=configuration.auto_disconnect_enabled,
        idle_timeout_seconds=configuration.idle_timeout_seconds,
        profile_dir_name=configuration.profile_dir_name,
    )


def _register_browser_tools(mcp: FastMCP[None], metadata: Sequence[ToolMetadata]) -> None:
    for tool in metadata:
        description = tool.description or ""
        if tool.name.startswith("local_"):
            description = "Local managed browser on the selected Briareus node. " + description
            if tool.name == "local_browser_status":
                description += (
                    " If starting=true, call this same status tool again at least every two "
                    "seconds until running=true. Each call requires current rights; without "
                    "fresh status authority preparation pauses within five seconds. "
                    "Other browser effects wait for preparation."
                )
        elif tool.name.startswith("external_"):
            description = (
                "Connected external browser configured for this node placement. " + description
            )
        mcp.add_tool(
            Tool(
                name=tool.name,
                title=tool.title,
                description=description,
                parameters=tool.input_schema,
                output_schema=tool.output_schema,
                annotations=tool.annotations,
                meta=tool.meta,
                icons=tool.icons,
            )
        )
    register_operations(mcp)


def create_app(spec: Deployment) -> ASGIApp:
    require_supervisor_isolation()
    if spec.release.module != "web" or spec.release.run_as != "1000:1000":
        raise ValueError("Approved isolated Node Web placement required")
    configuration = spec.configuration.browser if spec.configuration is not None else None
    supervisor = WebSupervisor(
        browser_policy=_browser_policy(configuration),
        developer_access_enabled=configuration.developer_access_enabled if configuration else False,
        project_workspace=spec.project_workspace is not None,
        project_workspace_read_only=spec.project_workspace.read_only
        if spec.project_workspace
        else False,
    )

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        watchdog: asyncio.Task[None] | None = None
        try:
            await supervisor.start()
            watchdog = asyncio.create_task(supervisor.watchdog())
            yield
        finally:
            if watchdog is not None:
                watchdog.cancel()
                with suppress(asyncio.CancelledError):
                    await watchdog
            await supervisor.stop()

    async def execute(
        call: CallToolRequestParams,
        permit: EffectPermit,
    ) -> CallToolResult:
        try:
            reply = await supervisor.execute(call, permit)
            if reply.result is None:
                raise ValueError("Browser operation failed")
            return reply.result
        except NodePreparing:
            raise
        except (OSError, ValueError, KeyError):
            raise ToolError("WEB_OUTCOME_UNAVAILABLE") from None

    app = create_node_app(
        spec,
        register_tools=lambda mcp: _register_browser_tools(mcp, supervisor.metadata),
        execute=execute,
        execute_human=execute,
        lifespan=lifespan,
        # The supervisor retains its validated catalogue while replacing a
        # private child. Authorized status calls drive preparation during that
        # interval; execution still requires the child's readiness and permit.
        ready=lambda: bool(supervisor.metadata),
    )
    core_key = os.environ.get("BRIAREUS_CORE_VERIFY_KEY")
    return BrowserObservationBoundary(
        app,
        spec,
        supervisor.observations,
        CoreVerifier(core_key.encode(), spec.node_uuid) if core_key else None,
    )


def main() -> None:
    run_node_app(create_app, module="web")


if __name__ == "__main__":
    main()
