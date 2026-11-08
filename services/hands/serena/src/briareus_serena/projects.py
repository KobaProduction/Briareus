"""One isolated Serena stdio process and configuration directory per Server project."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from briareus_json_values import JsonObject
from briareus_mcp_client.mcp_client_pool import PersistentMcpClientPool, SessionClient
from fastmcp import Client
from fastmcp.client.client import CallToolResult
from fastmcp.client.transports import StdioTransport

from .models import ProjectRegistry, ProjectSpec, ProjectStatus, SerenaSettings


@dataclass
class ProjectProcess:
    pool: PersistentMcpClientPool
    last_used: float
    active_calls: int = 0


class ProjectManager:
    def __init__(
        self,
        settings: SerenaSettings,
        *,
        factory: Callable[[ProjectSpec], SessionClient] | None = None,
    ) -> None:
        self.settings = settings
        settings.state_root.mkdir(parents=True, exist_ok=True)
        self.registry_path = settings.state_root / "projects.json"
        registry = (
            ProjectRegistry.model_validate_json(self.registry_path.read_bytes())
            if self.registry_path.exists()
            else ProjectRegistry()
        )
        self.projects = {p.project_id: p for p in [*registry.projects, *settings.projects]}
        self.processes: dict[str, ProjectProcess] = {}
        self.lock = asyncio.Lock()
        self.closed = False
        self._factory = factory or self.client
        self._tasks: set[asyncio.Task[CallToolResult]] = set()

    def resolve_folder(self, folder: str) -> Path:
        root = self.settings.workspace_root.resolve()
        path = (root / folder).resolve()
        if not path.is_relative_to(root) or not path.is_dir():
            raise ValueError("Project folder must be an existing directory inside Server workspace")
        return path

    def _save(self) -> None:
        registry = ProjectRegistry(projects=list(self.projects.values()))
        temporary = self.registry_path.with_suffix(".tmp")
        temporary.write_text(registry.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(self.registry_path)

    async def register(self, project: ProjectSpec) -> ProjectStatus:
        folder = self.resolve_folder(project.folder)
        project = project.model_copy(update={"folder": str(folder)})
        async with self.lock:
            if any(
                p.project_id != project.project_id
                and (self.settings.workspace_root / p.folder).resolve() == folder
                for p in self.projects.values()
            ):
                raise ValueError("This Server folder is already registered under another project")
            old = self.projects.get(project.project_id)
            if old != project and project.project_id in self.processes:
                raise ValueError("Close the project's process before changing its folder")
            self.projects[project.project_id] = project
            self._save()
            return self.status(project)

    def status(self, project: ProjectSpec) -> ProjectStatus:
        process = self.processes.get(project.project_id)
        return ProjectStatus(
            project=project,
            state="stopped" if process is None else "busy" if process.active_calls else "running",
            active_calls=process.active_calls if process else 0,
            idle_seconds=max(0, time.monotonic() - process.last_used) if process else 0,
        )

    def client(self, project: ProjectSpec | None = None) -> Client[StdioTransport]:
        home = self.settings.state_root / (project.project_id if project else "catalog")
        home.mkdir(parents=True, exist_ok=True)
        args = [
            "start-mcp-server",
            "--transport",
            "stdio",
            "--context",
            "desktop-app",
            "--agent-interface",
            "tools",
            "--enable-web-dashboard",
            "false",
        ]
        if project:
            args += ["--project", str(self.resolve_folder(project.folder))]
        return Client(
            StdioTransport(
                command=self.settings.command,
                args=args,
                cwd=str(self.settings.workspace_root),
                env={
                    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                    "HOME": str(home),
                    "SERENA_HOME": str(home),
                    "SERENA_DOCKER": "1",
                },
            ),
            timeout=300,
        )

    async def _start(self, project: ProjectSpec) -> ProjectProcess:
        if len(self.processes) >= self.settings.max_processes:
            idle = [
                (key, process)
                for key, process in self.processes.items()
                if not process.active_calls
            ]
            if not idle:
                raise ValueError("Serena project process limit reached; all processes are busy")
            key, _ = min(idle, key=lambda item: item[1].last_used)
            await self._close(key)
        process = ProjectProcess(
            PersistentMcpClientPool(
                lambda: self._factory(project),
                name=f"serena:{project.project_id}",
                size=1,
            ),
            time.monotonic(),
        )
        self.processes[project.project_id] = process
        return process

    async def call_tool(self, name: str, arguments: JsonObject) -> CallToolResult:
        project_id = arguments.get("project_id")
        if not isinstance(project_id, str):
            raise ValueError("A registered project_id is required")
        async with self.lock:
            if self.closed:
                raise ValueError("Serena is shutting down")
            project = self.projects.get(project_id)
            if project is None:
                raise ValueError("Register the Server project folder before calling Serena tools")
            self.resolve_folder(project.folder)
            process = self.processes.get(project_id) or await self._start(project)
            process.active_calls += 1
            forwarded = {key: value for key, value in arguments.items() if key != "project_id"}
            task = asyncio.create_task(process.pool.call_tool(name, forwarded, timeout_seconds=0))
            self._tasks.add(task)
        try:
            return await task
        finally:
            async with self.lock:
                process.active_calls -= 1
                process.last_used = time.monotonic()
                self._tasks.discard(task)

    async def _close(self, project_id: str) -> None:
        process = self.processes.get(project_id)
        if process is not None:
            if process.active_calls:
                raise ValueError("Project has active operations; it cannot be stopped")
            await process.pool.close()
            self.processes.pop(project_id)

    async def close_project(self, project_id: str) -> None:
        async with self.lock:
            await self._close(project_id)

    async def unregister(self, project_id: str) -> None:
        async with self.lock:
            await self._close(project_id)
            self.projects.pop(project_id, None)
            self._save()

    async def reap_idle(self) -> None:
        while True:
            await asyncio.sleep(15)
            await self.reap_idle_projects()

    async def reap_idle_projects(self) -> None:
        async with self.lock:
            for key, process in list(self.processes.items()):
                if (
                    not process.active_calls
                    and time.monotonic() - process.last_used >= self.settings.idle_seconds
                ):
                    await self._close(key)

    async def close(self) -> None:
        async with self.lock:
            self.closed = True
            tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        async with self.lock:
            for key in list(self.processes):
                await self._close(key)
