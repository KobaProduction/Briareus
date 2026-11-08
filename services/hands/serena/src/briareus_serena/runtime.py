"""Project-scoped Serena tools using Server's shared filesystem."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager, suppress

from briareus_control_panel_client.settings import ControlPanelClientSettings
from briareus_hand_runtime.runtime_common import (
    build_private_mcp,
    management_client,
    private_http_app,
)
from briareus_hand_runtime.settings import PrivateRuntimeSettings
from briareus_mcp_client.provider_tools import forwarded_tool
from fastmcp.server.providers import Provider
from fastmcp.tools import Tool
from starlette.applications import Starlette

from .models import ProjectSpec, ProjectStatus, SerenaSettings
from .projects import ProjectManager

_BLOCKED_TOOLS = {
    "activate_project",
    "execute_shell_command",
    "switch_modes",
    "register_project",
    "list_projects",
    "stop_project",
    "unregister_project",
    "serena_repl",
    "remove_project",
    "open_dashboard",
}


class ProjectTools(Provider):
    def __init__(self, manager: ProjectManager) -> None:
        super().__init__()
        self.manager = manager
        self.catalog: list[Tool] | None = None
        self.lock = asyncio.Lock()

    async def _list_tools(self) -> Sequence[Tool]:
        async with self.lock:
            if self.catalog is None:
                async with self.manager.client() as client:
                    tools = await client.list_tools()
                self.catalog = [
                    forwarded_tool(tool, self.manager.call_tool, project_scoped=True)
                    for tool in tools
                    if tool.name not in _BLOCKED_TOOLS
                ]
            return self.catalog


manager = ProjectManager(SerenaSettings())
mcp = build_private_mcp("serena", management_client(ControlPanelClientSettings()))
mcp.add_provider(ProjectTools(manager))


@mcp.tool
async def register_project(project_id: str, folder: str) -> ProjectStatus:
    """Register an existing Server workspace folder; each project gets its own Serena process."""
    return await manager.register(ProjectSpec(project_id=project_id, folder=folder))


@mcp.tool
async def list_projects() -> list[ProjectStatus]:
    """List registered Server projects, active operations and idle process state."""
    async with manager.lock:
        return [manager.status(project) for project in manager.projects.values()]


@mcp.tool
async def stop_project(project_id: str) -> None:
    """Stop one idle project process; source files and registration remain intact."""
    await manager.close_project(project_id)


@mcp.tool
async def unregister_project(project_id: str) -> None:
    """Stop and unregister one project without deleting its Server files."""
    await manager.unregister(project_id)


app = private_http_app(mcp, PrivateRuntimeSettings())
_lifespan = app.router.lifespan_context


@asynccontextmanager
async def lifespan(application: Starlette) -> AsyncIterator[None]:
    async with _lifespan(application):
        reaper = asyncio.create_task(manager.reap_idle(), name="serena-idle-projects")
        try:
            yield
        finally:
            reaper.cancel()
            with suppress(asyncio.CancelledError):
                await reaper
            await manager.close()


app.router.lifespan_context = lifespan
