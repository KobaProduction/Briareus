"""Prepare every bound workspace in order before the worker is created."""

from typing import Protocol

from node_agent.domain.workspace import WorkspaceIdentity

from ._runtime_binding import _RuntimeBinding


class WorkspacePreparationPort(Protocol):
    async def prepare(self, workspace: WorkspaceIdentity) -> None: ...


class PrepareWorkspaces(_RuntimeBinding[WorkspacePreparationPort]):
    async def execute(self, workspaces: tuple[WorkspaceIdentity, ...]) -> None:
        for workspace in workspaces:
            await self.runtime.prepare(workspace)
