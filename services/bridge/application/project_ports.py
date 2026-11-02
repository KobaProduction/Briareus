"""Project effect capabilities; concrete Files/selector services stay outside."""

from typing import Protocol
from uuid import UUID

from bridge.application.project_contracts import (
    FileEntry,
    FilePage,
    IntegrationMetadata,
    ResourceProvider,
    ResourceScope,
    VariableMetadata,
    WriteLedgerState,
)
from modules.project_runtime import ProjectInvocation, ProjectPermit


class ProjectFilesPort(Protocol):
    def require_signed(self) -> None: ...

    async def list(
        self,
        invocation: ProjectInvocation,
        path: str,
        *,
        offset: int,
        limit: int,
    ) -> FilePage: ...

    async def info(self, invocation: ProjectInvocation, path: str) -> FileEntry: ...

    async def sha256(self, invocation: ProjectInvocation, path: str) -> str: ...

    async def read(self, invocation: ProjectInvocation, path: str, *, max_bytes: int) -> bytes: ...

    async def write(
        self,
        invocation: ProjectInvocation,
        destination: str,
        body: bytes,
        *,
        operation_uuid: UUID,
    ) -> FileEntry: ...

    async def inspect(
        self,
        invocation: ProjectInvocation,
        *,
        initial: ProjectPermit,
        destination: str,
        operation_uuid: UUID,
    ) -> WriteLedgerState | None: ...


class ProjectIntegrationsPort(Protocol):
    async def list(
        self,
        invocation: ProjectInvocation,
        *,
        provider: ResourceProvider,
        scope: ResourceScope,
        owner_id: UUID | None,
    ) -> tuple[IntegrationMetadata, ...]: ...


class ProjectVariablesPort(Protocol):
    async def list_metadata(
        self,
        invocation: ProjectInvocation,
        *,
        scope: ResourceScope,
        owner_id: UUID | None,
    ) -> tuple[VariableMetadata, ...]: ...
