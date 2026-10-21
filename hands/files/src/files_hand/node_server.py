"""Complete original Files MCP surface with per-effect Core authority."""
from __future__ import annotations

import json
import os
import time
from contextlib import asynccontextmanager

from hand_runtime.node_adapter import create_node_app
from node_protocol import Deployment

from .node_dispatch import FileDispatch, register_original_tools
from .node_workspace import NodeWorkspace


def create_app(spec, root="/project-data"):
    if os.getuid() != 1000 or spec.release.run_as != "1000:1000" or spec.release.module != "files":
        raise ValueError("Non-root isolated Files placement required")
    workspace = NodeWorkspace(root)
    dispatch = FileDispatch(workspace)

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            workspace.close()

    async def execute(tool_name, arguments, permit):
        # Every descriptor step and atomic commit checks this deadline.
        from hand_runtime.runtime_policy import runtime_policy
        limit=runtime_policy().execution_timeout_seconds
        deadline=min(permit.expires_at,time.time()+limit) if limit is not None else permit.expires_at
        with workspace.authority(deadline):
            result = dispatch.call(tool_name, arguments)
        return {"content": [{"type": "text", "text": json.dumps(result, allow_nan=False)}],
                "structuredContent": result, "isError": False}

    return create_node_app(spec, register_tools=lambda mcp: register_original_tools(mcp, workspace),
                           execute=execute, lifespan=lifespan)


def main():
    import uvicorn
    spec = Deployment.model_validate_json(os.environ["BRIAREUS_DEPLOYMENT"])
    # Preserve the existing unprivileged Files TCP execution placement.
    uvicorn.run(create_app(spec), host="0.0.0.0", port=spec.release.port, access_log=False)


if __name__ == "__main__":
    main()
