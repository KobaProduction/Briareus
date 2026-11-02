"""Complete original Files MCP surface with per-effect Core authority."""

from __future__ import annotations

import os
import socket
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.types import CallToolRequestParams, CallToolResult
from starlette.applications import Starlette

from hand_runtime.node_adapter import create_node_app
from hand_runtime.node_boundary import EffectBoundary
from node_protocol import Deployment
from node_protocol.effect import EffectPermit

from .node_dispatch import FileDispatch, register_original_tools
from .node_workspace import NodeWorkspace
from .presentation.tool_registry import McpFilesToolRegistry


def create_app(spec: Deployment, root: str | Path = "/project-data") -> EffectBoundary:
    if os.getuid() != 1000 or spec.release.run_as != "1000:1000" or spec.release.module != "files":
        raise ValueError("Non-root isolated Files placement required")
    workspace = NodeWorkspace(root)
    dispatch = FileDispatch(workspace)

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        try:
            yield
        finally:
            workspace.close()

    async def execute(call: CallToolRequestParams, permit: EffectPermit) -> CallToolResult:
        # Every descriptor step and atomic commit checks this deadline.
        from hand_runtime.runtime_policy import runtime_policy

        limit = runtime_policy().execution_timeout_seconds
        deadline = (
            min(permit.expires_at, time.time() + limit) if limit is not None else permit.expires_at
        )
        with workspace.authority(deadline):
            return dispatch.call(call)

    return create_node_app(
        spec,
        register_tools=lambda mcp: register_original_tools(McpFilesToolRegistry(mcp), workspace),
        execute=execute,
        execute_human=execute,
        lifespan=lifespan,
    )


def main() -> None:
    import uvicorn

    spec = Deployment.model_validate_json(os.environ["BRIAREUS_DEPLOYMENT"])
    # Preserve the existing unprivileged Files TCP execution placement.
    uvicorn.run(
        create_app(spec),
        host=socket.inet_ntoa(socket.INADDR_ANY.to_bytes(4, byteorder="big")),
        port=spec.release.port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
