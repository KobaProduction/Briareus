"""Reauthorize each Project effect, then invoke only its bounded storage capability."""

from __future__ import annotations

import base64
import hashlib
from typing import cast

from bridge.application.project_contracts import (
    FileCommitted,
    FileContents,
    FileDigest,
    FileList,
    FilePath,
    FileRead,
    FileUnverified,
    FileUpload,
    FileWriteObservation,
    FileWriteStatus,
    IntegrationCatalog,
    ProjectResult,
    ResourceProvider,
    ResourceSelection,
    VariableCatalog,
)
from bridge.application.project_dispatch import (
    _PRIVATE_TOOL_ACTIONS,
    AuthorizedToolForward,
    ProjectDispatchAuthority,
)
from bridge.application.project_ports import (
    ProjectFilesPort,
    ProjectIntegrationsPort,
    ProjectVariablesPort,
)
from bridge.domain.project_dispatch import ProjectGatewayDispatchUnavailable
from bridge.domain.upload import decoded_upload
from modules.project_runtime import ProjectPermit


class ForwardProjectEffect:
    def __init__(
        self,
        authority: ProjectDispatchAuthority,
        *,
        files: ProjectFilesPort | None = None,
        integrations: ProjectIntegrationsPort | None = None,
        variables: ProjectVariablesPort | None = None,
    ) -> None:
        self.authority = authority
        self.files = files
        self.integrations = integrations
        self.variables = variables

    async def forward(self, request: AuthorizedToolForward) -> ProjectResult:
        action = _PRIVATE_TOOL_ACTIONS.get((request.backend, request.tool))
        if action is None or action != request.permit.action:
            raise ProjectGatewayDispatchUnavailable("PROJECT_TOOL_NOT_AUTHORIZED")
        current = await self.authority.require(request.invocation, action)
        self._require_same_authority(current, request.permit)
        if request.backend == "files":
            return await self._files(request, current)
        if not isinstance(request.arguments, ResourceSelection):
            raise ProjectGatewayDispatchUnavailable("PROJECT_ARGUMENTS_INVALID")
        if request.backend in {"github", "gitlab", "observability"}:
            return await self._integrations(request, request.arguments)
        if request.backend == "variables" and request.tool == "metadata":
            return await self._variables(request, request.arguments)
        raise ProjectGatewayDispatchUnavailable("PROJECT_TOOL_NOT_AUTHORIZED")

    @staticmethod
    def _require_same_authority(current: ProjectPermit, previous: ProjectPermit) -> None:
        current_scope = (
            current.project_id,
            current.actor_id,
            current.session_uuid,
            current.project_access_revision,
            current.decision_version,
            current.project_owner_id,
            current.project_owner_scope,
        )
        previous_scope = (
            previous.project_id,
            previous.actor_id,
            previous.session_uuid,
            previous.project_access_revision,
            previous.decision_version,
            previous.project_owner_id,
            previous.project_owner_scope,
        )
        if current_scope != previous_scope:
            raise ProjectGatewayDispatchUnavailable("PROJECT_ACCESS_STALE")

    async def _files(self, request: AuthorizedToolForward, current: ProjectPermit) -> ProjectResult:
        files = self.files
        if files is None:
            raise ProjectGatewayDispatchUnavailable("PROJECT_FILES_NOT_CONFIGURED")
        command = request.arguments
        if request.tool == "list" and isinstance(command, FileList):
            return await files.list(
                request.invocation,
                command.path,
                offset=command.offset,
                limit=command.limit,
            )
        if request.tool == "info" and isinstance(command, FilePath):
            return await files.info(request.invocation, command.path)
        if request.tool == "sha256" and isinstance(command, FilePath):
            digest = await files.sha256(request.invocation, command.path)
            return FileDigest(command.path, digest)
        if request.tool == "read_base64" and isinstance(command, FileRead):
            contents = await files.read(
                request.invocation, command.path, max_bytes=command.max_bytes
            )
            return FileContents(
                command.path,
                base64.b64encode(contents).decode("ascii"),
                len(contents),
                hashlib.sha256(contents).hexdigest(),
            )
        if request.tool == "upload_base64" and isinstance(command, FileUpload):
            return await self._upload(files, request, command)
        if request.tool == "write_status" and isinstance(command, FileWriteStatus):
            return await self._status(files, request, current, command)
        raise ProjectGatewayDispatchUnavailable("PROJECT_ARGUMENTS_INVALID")

    @staticmethod
    async def _upload(
        files: ProjectFilesPort,
        request: AuthorizedToolForward,
        command: FileUpload,
    ) -> FileCommitted:
        files.require_signed()
        if command.operation_uuid.version != 4 or command.operation_uuid != request.request_uuid:
            raise ProjectGatewayDispatchUnavailable("PROJECT_REQUEST_UUID_MISMATCH")
        body = decoded_upload(
            command.content_base64,
            size_bytes=command.size_bytes,
            sha256=command.sha256,
        )
        try:
            saved = await files.write(
                request.invocation,
                command.destination,
                body,
                operation_uuid=request.request_uuid,
            )
        except Exception as exc:
            raise ProjectGatewayDispatchUnavailable(
                "PROJECT_FILE_OUTCOME_UNKNOWN",
                operation_uuid=request.request_uuid,
            ) from exc
        if saved.kind != "file" or saved.size_bytes != len(body):
            raise ProjectGatewayDispatchUnavailable("PROJECT_FILE_COMMIT_UNCERTAIN")
        return FileCommitted(request.request_uuid, saved.path, saved.size_bytes, command.sha256)

    @staticmethod
    async def _status(
        files: ProjectFilesPort,
        request: AuthorizedToolForward,
        current: ProjectPermit,
        command: FileWriteStatus,
    ) -> FileUnverified | FileWriteObservation:
        if command.operation_uuid != request.request_uuid:
            raise ProjectGatewayDispatchUnavailable("PROJECT_REQUEST_UUID_MISMATCH")
        files.require_signed()
        try:
            inspected = await files.inspect(
                request.invocation,
                initial=current,
                destination=command.destination,
                operation_uuid=request.request_uuid,
            )
        except Exception as exc:
            raise ProjectGatewayDispatchUnavailable(
                "PROJECT_FILE_STATUS_UNAVAILABLE",
                operation_uuid=request.request_uuid,
            ) from exc
        if inspected is None:
            return FileUnverified(request.request_uuid)
        return FileWriteObservation(
            request.request_uuid,
            inspected.status,
            inspected.reservation_version,
            inspected.requested_bytes,
            inspected.expires_at,
            inspected.status in {"dispatched", "unknown"},
        )

    async def _integrations(
        self,
        request: AuthorizedToolForward,
        command: ResourceSelection,
    ) -> IntegrationCatalog:
        if self.integrations is None:
            raise ProjectGatewayDispatchUnavailable("PROJECT_INTEGRATIONS_NOT_CONFIGURED")
        provider: ResourceProvider
        if request.backend == "observability":
            if command.provider is None:
                raise ProjectGatewayDispatchUnavailable("PROJECT_ARGUMENTS_INVALID")
            provider = command.provider
        else:
            provider = cast(ResourceProvider, request.backend)
        connections = await self.integrations.list(
            request.invocation,
            provider=provider,
            scope=command.scope,
            owner_id=command.owner_id,
        )
        return IntegrationCatalog(connections)

    async def _variables(
        self,
        request: AuthorizedToolForward,
        command: ResourceSelection,
    ) -> VariableCatalog:
        if self.variables is None:
            raise ProjectGatewayDispatchUnavailable("PROJECT_VARIABLES_NOT_CONFIGURED")
        variables = await self.variables.list_metadata(
            request.invocation,
            scope=command.scope,
            owner_id=command.owner_id,
        )
        return VariableCatalog(variables)
