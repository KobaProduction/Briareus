"""Composition and concrete adapters for independently authorized Project effects."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from bridge.application.project_contracts import (
    FileEntry,
    FilePage,
    IntegrationMetadata,
    ProjectCommand,
    ProjectResult,
    ResourceProvider,
    ResourceScope,
    VariableMetadata,
    WriteLedgerState,
)
from bridge.application.project_dispatch import (
    _PRIVATE_TOOL_ACTIONS,
    AuthorizedToolForward,
    ProjectDispatchAuthority,
)
from bridge.application.project_effects import ForwardProjectEffect
from bridge.domain.project_dispatch import ProjectGatewayDispatchUnavailable
from bridge.infrastructure.project_codec import command_fingerprint
from modules.project_runtime import ProjectAction, ProjectInvocation, ProjectPermit

if TYPE_CHECKING:
    from modules.files.project_files import ProjectFilesService
    from modules.project_runtime.integrations import ProjectIntegrationSelector
    from modules.project_runtime.variables import ProjectVariableSelector


class PrivateProjectToolClassifier:
    async def classify(self, backend: str, tool: str) -> ProjectAction | None:
        return _PRIVATE_TOOL_ACTIONS.get((backend, tool))


class ProjectFilesAdapter:
    def __init__(self, files: ProjectFilesService) -> None:
        self._files = files

    def require_signed(self) -> None:
        if self._files.a6_quota is None:
            raise ProjectGatewayDispatchUnavailable("PROJECT_SIGNED_FILES_UNAVAILABLE")

    async def list(
        self,
        invocation: ProjectInvocation,
        path: str,
        *,
        offset: int,
        limit: int,
    ) -> FilePage:
        page = await self._files.list(invocation, path, offset=offset, limit=limit)
        return FilePage(
            tuple(
                FileEntry(entry.path, entry.kind, entry.size_bytes, entry.modified_at_ns)
                for entry in page.entries
            ),
            page.total,
            page.offset,
            page.limit,
        )

    async def info(self, invocation: ProjectInvocation, path: str) -> FileEntry:
        info = await self._files.info(invocation, path)
        return FileEntry(info.path, info.kind, info.size_bytes, info.modified_at_ns)

    async def sha256(self, invocation: ProjectInvocation, path: str) -> str:
        return await self._files.sha256(invocation, path)

    async def read(self, invocation: ProjectInvocation, path: str, *, max_bytes: int) -> bytes:
        return await self._files.read(invocation, path, max_bytes=max_bytes)

    async def write(
        self,
        invocation: ProjectInvocation,
        destination: str,
        body: bytes,
        *,
        operation_uuid: UUID,
    ) -> FileEntry:
        saved = await self._files.write(
            invocation, destination, body, operation_uuid=operation_uuid
        )
        return FileEntry(saved.path, saved.kind, saved.size_bytes, saved.modified_at_ns)

    async def inspect(
        self,
        invocation: ProjectInvocation,
        *,
        initial: ProjectPermit,
        destination: str,
        operation_uuid: UUID,
    ) -> WriteLedgerState | None:
        inspected = await self._files.a6_quota.inspect(
            invocation,
            initial=initial,
            destination=destination,
            operation_uuid=operation_uuid,
        )
        if inspected is None:
            return None
        return WriteLedgerState(
            inspected.status,
            inspected.reservation_version,
            inspected.requested_bytes,
            inspected.expires_at,
        )


class ProjectIntegrationAdapter:
    def __init__(self, integrations: ProjectIntegrationSelector) -> None:
        self._integrations = integrations

    async def list(
        self,
        invocation: ProjectInvocation,
        *,
        provider: ResourceProvider,
        scope: ResourceScope,
        owner_id: UUID | None,
    ) -> tuple[IntegrationMetadata, ...]:
        connections = await self._integrations.list(
            invocation,
            provider=provider,
            scope=scope,
            owner_id=owner_id,
        )
        return tuple(
            IntegrationMetadata(
                ref.resource_id,
                ref.name,
                ref.provider,
                ref.credential_type,
                ref.scope.owner_scope,
                ref.scope.owner_id,
                ref.scope.inherited,
                ref.scope.resource_revision,
            )
            for ref in connections
        )


class ProjectVariableAdapter:
    def __init__(self, variables: ProjectVariableSelector) -> None:
        self._variables = variables

    async def list_metadata(
        self,
        invocation: ProjectInvocation,
        *,
        scope: ResourceScope,
        owner_id: UUID | None,
    ) -> tuple[VariableMetadata, ...]:
        variables = await self._variables.list_metadata(invocation, scope=scope, owner_id=owner_id)
        return tuple(
            VariableMetadata(
                ref.resource_id,
                ref.name,
                ref.kind,
                ref.scope.owner_scope,
                ref.scope.owner_id,
                ref.scope.inherited,
                ref.scope.resource_revision,
            )
            for ref in variables
        )


class PrivateProjectModuleForwarder:
    def __init__(
        self,
        authority: ProjectDispatchAuthority,
        *,
        files: ProjectFilesService | None = None,
        integrations: ProjectIntegrationSelector | None = None,
        variables: ProjectVariableSelector | None = None,
    ) -> None:
        self._effects = ForwardProjectEffect(
            authority,
            files=ProjectFilesAdapter(files) if files is not None else None,
            integrations=ProjectIntegrationAdapter(integrations)
            if integrations is not None
            else None,
            variables=ProjectVariableAdapter(variables) if variables is not None else None,
        )

    def fingerprint(
        self,
        invocation: ProjectInvocation,
        action: ProjectAction,
        request_uuid: UUID,
        backend: str,
        tool: str,
        command: ProjectCommand,
    ) -> str:
        return command_fingerprint(invocation, action, request_uuid, backend, tool, command)

    async def forward(self, request: AuthorizedToolForward) -> ProjectResult:
        return await self._effects.forward(request)
