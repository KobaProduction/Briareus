"""Node Web MCP metadata wrapper; effects execute only in the private child."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from mcp.types import Tool as ToolMetadata

from hand_runtime.node_adapter import create_node_app, run_node_app

from .node_supervisor import WebSupervisor, require_supervisor_isolation
from .operations import register_operations


class MetadataTool(Tool):
    async def run(self, arguments):
        raise ToolError("WEB_PRIVATE_CHILD_REQUIRED")


def create_app(spec):
    require_supervisor_isolation()
    if spec.release.module != "web" or spec.release.run_as != "1000:1000":
        raise ValueError("Approved isolated Node Web placement required")
    configuration = getattr(spec, "configuration", None)
    browser_configuration = (configuration.get("browser", {}) if isinstance(configuration, dict)
        else getattr(configuration, "browser", {}))
    if hasattr(browser_configuration, "model_dump"):
        browser_configuration = browser_configuration.model_dump(mode="json")
    browser_configuration = dict(browser_configuration or {})
    developer_access = browser_configuration.pop("developer_access_enabled", False)
    supervisor = WebSupervisor(browser_policy=browser_configuration, developer_access_enabled=developer_access, project_workspace=spec.project_workspace is not None,
        project_workspace_read_only=spec.project_workspace.read_only if spec.project_workspace else False)

    @asynccontextmanager
    async def lifespan(_app):
        watchdog = None
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

    async def register_tools(mcp):
        for raw in supervisor.metadata:
            tool = ToolMetadata.model_validate(raw)
            description = tool.description or ""
            if tool.name.startswith("local_"):
                description = "Local managed browser on the selected Briareus node. " + description
                if tool.name == "local_browser_status":
                    description += " If starting=true, call this same status tool again at least every two seconds until running=true. Each call requires current rights; without fresh status authority preparation pauses within five seconds. Other browser effects wait for preparation."
            elif tool.name.startswith("external_"):
                description = "Connected external browser configured for this node placement. " + description
            mcp.add_tool(MetadataTool(name=tool.name, title=tool.title, description=description,
                parameters=tool.input_schema, output_schema=tool.output_schema, annotations=tool.annotations,
                meta=tool.meta, icons=tool.icons))
        register_operations(mcp)

    async def execute(tool_name, arguments, permit):
        try:
            reply = await supervisor.execute(tool_name, arguments, permit)
            if "result" not in reply:
                raise ValueError("Browser operation failed")
            return reply["result"]
        except (OSError, ValueError, KeyError):
            raise ToolError("WEB_OUTCOME_UNAVAILABLE") from None

    return create_node_app(spec, register_tools=register_tools, execute=execute,
        lifespan=lifespan, ready=lambda: supervisor.child_ready and supervisor.child is not None
        and supervisor.child.returncode is None)


def main():
    run_node_app(create_app, module="web")


if __name__ == "__main__":
    main()
