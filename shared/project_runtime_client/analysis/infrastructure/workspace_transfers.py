from __future__ import annotations

import base64
import binascii
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from pydantic import BaseModel

from project_runtime_client.analysis.application.workspace_io import AnalysisWorkspacePort
from project_runtime_client.analysis.application.workspace_transfers import WorkspaceTransfers
from project_runtime_client.analysis.configuration import AnalysisBackendConfiguration
from project_runtime_client.analysis.domain.artifacts import (
    ArtifactContent,
    StagedWorkspaceArtifact,
    WorkspaceArtifactExport,
    WorkspaceImportReceipt,
)
from project_runtime_client.analysis.domain.workspace import WorkspaceFileMetadata
from project_runtime_client.workspace_compat.domain.receipts import WorkspaceFileEntry
from project_runtime_client.workspace_compat.infrastructure.filesystem import WorkspaceFileStore
from service_runtime._runtime_reference_bindings import _WorkspaceBinding
from service_runtime.mcp_client_pool import PersistentMcpClientPool
from service_runtime.mcp_http import mcp_http_client

from .artifact_client import call_artifact
from .artifact_commands import (
    ArchiveProject,
    ArtifactCommand,
    BeginArtifact,
    CancelArtifact,
    DeleteArtifact,
    ExportProgram,
    FinishArtifact,
    ImportBinary,
    ImportProgram,
    ReadArtifact,
    RestoreProject,
    WriteArtifact,
)
from .artifact_replies import (
    ArtifactChunk,
    ArtifactExportPath,
    DirectArtifactReceipt,
    ImportedBinaryReply,
    ImportedProgramReply,
    RestoredProjectReply,
    StageFinished,
    StageOpened,
    StageWritten,
    TransferAcknowledgement,
)


class AnalysisTransferError(RuntimeError):
    pass


class AnalysisWorkspaceTransfers(WorkspaceTransfers):
    """Copy selected files across the isolated analysis-runtime boundary."""

    def __init__(
        self,
        settings: AnalysisBackendConfiguration,
        workspace: AnalysisWorkspacePort,
        *,
        max_file_bytes: int,
        chunk_bytes: int = 1024 * 1024,
    ) -> None:
        self.settings = settings
        self._workspace = workspace
        self.max_file_bytes = max_file_bytes
        self.chunk_bytes = chunk_bytes
        self._backend_pool = PersistentMcpClientPool(
            self._client,
            name="analysis-transfer-ghidra",
            size=2,
        )

    def _client(self) -> Client[StreamableHttpTransport]:
        transport = StreamableHttpTransport(
            self.settings.backend_url,
            headers={"X-Koba-Proxy-Origin": "analysis"},
            httpx_client_factory=mcp_http_client,
        )
        return Client(transport, timeout=None)

    async def _call[T: BaseModel](self, command: ArtifactCommand, response_type: type[T]) -> T:
        try:
            return await call_artifact(self._backend_pool, command, response_type)
        except ValueError as exc:
            raise AnalysisTransferError(str(exc)) from exc

    async def _direct_upload_workspace_file(
        self,
        project_id: str,
        workspace_path: str,
    ) -> StagedWorkspaceArtifact:
        source = self._workspace.path_for(workspace_path)
        if not source.is_file():
            raise AnalysisTransferError("workspace path is not a file")
        size = source.stat().st_size
        if size > self.max_file_bytes:
            raise AnalysisTransferError("workspace file exceeds configured size limit")
        digest = self._workspace.sha256(workspace_path)
        upload_url = self.settings.direct_upload_url.strip()
        if not upload_url:
            raise AnalysisTransferError("direct artifact upload is not configured")

        async def chunks() -> AsyncIterator[bytes]:
            with source.open("rb") as handle:
                while True:
                    chunk = handle.read(max(self.chunk_bytes, 4 * 1024 * 1024))
                    if not chunk:
                        break
                    yield chunk

        timeout = httpx.Timeout(self.settings.direct_upload_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                upload_url,
                params={"project_id": project_id, "name": source.name},
                headers={
                    "X-Koba-Proxy-Origin": "analysis",
                    "X-Artifact-Size": str(size),
                    "X-Artifact-SHA256": digest,
                    "Content-Type": "application/octet-stream",
                },
                content=chunks(),
            )
        if response.status_code >= 400:
            raise AnalysisTransferError(
                f"direct artifact upload failed with HTTP {response.status_code}"
            )
        receipt = DirectArtifactReceipt.model_validate_json(response.content)
        ArtifactContent(size, digest).require_match(receipt.content)
        if not receipt.success or receipt.project_id != project_id:
            raise AnalysisTransferError("Artifact receipt does not belong to this project")
        return StagedWorkspaceArtifact(
            path=receipt.path,
            workspace_path=workspace_path,
            size_bytes=size,
            sha256=digest,
            transfer_method="direct_raw",
        )

    async def _transfer_workspace_file(
        self,
        project_id: str,
        workspace_path: str,
    ) -> StagedWorkspaceArtifact:
        direct_error = ""
        if self.settings.direct_upload_url.strip():
            try:
                return await self._direct_upload_workspace_file(project_id, workspace_path)
            except Exception as exc:
                direct_error = str(exc)

        staged = await self._stage_workspace_file(project_id, workspace_path)
        return replace(staged, direct_upload_error=direct_error)

    async def _stage_workspace_file(
        self,
        project_id: str,
        workspace_path: str,
    ) -> StagedWorkspaceArtifact:
        source = self._workspace.path_for(workspace_path)
        if not source.is_file():
            raise AnalysisTransferError("workspace path is not a file")
        size = source.stat().st_size
        if size > self.max_file_bytes:
            raise AnalysisTransferError("workspace file exceeds configured size limit")
        digest = self._workspace.sha256(workspace_path)
        begun = await self._call(
            BeginArtifact(project_id=project_id, name=source.name, size_bytes=size, sha256=digest),
            response_type=StageOpened,
        )
        stage_id = begun.stage_id
        if not stage_id:
            raise AnalysisTransferError("analysis backend did not return stage_id")

        try:
            offset = 0
            with source.open("rb") as handle:
                while True:
                    chunk = handle.read(self.chunk_bytes)
                    if not chunk:
                        break
                    written = await self._call(
                        WriteArtifact(
                            project_id=project_id,
                            stage_id=stage_id,
                            offset=offset,
                            data_base64=base64.b64encode(chunk).decode("ascii"),
                        ),
                        response_type=StageWritten,
                    )
                    next_offset = written.next_offset
                    if next_offset != offset + len(chunk):
                        raise AnalysisTransferError(
                            "analysis artifact stage did not advance offset"
                        )
                    offset = next_offset
            finished = await self._call(
                FinishArtifact(project_id=project_id, stage_id=stage_id),
                response_type=StageFinished,
            )
            ArtifactContent(size, digest).require_match(finished.content)
        except Exception:
            with suppress(Exception):
                await self._call(
                    CancelArtifact(project_id=project_id, stage_id=stage_id),
                    response_type=TransferAcknowledgement,
                )
            raise

        path = finished.path
        if not path:
            raise AnalysisTransferError("analysis backend did not return staged path")
        return StagedWorkspaceArtifact(
            stage_id=stage_id,
            path=path,
            workspace_path=workspace_path,
            size_bytes=size,
            sha256=digest,
            transfer_method="mcp_base64",
        )

    async def _cancel_stage(self, project_id: str, stage_id: str) -> None:
        await self._call(
            CancelArtifact(project_id=project_id, stage_id=stage_id),
            response_type=TransferAcknowledgement,
        )

    async def _cancel_stage_best_effort(
        self,
        project_id: str,
        stage_id: str,
    ) -> str:
        try:
            await self._cancel_stage(project_id, stage_id)
        except Exception as exc:
            return str(exc)
        return ""

    async def _cleanup_transfer_best_effort(
        self,
        project_id: str,
        transferred: StagedWorkspaceArtifact,
    ) -> str:
        try:
            if transferred.transfer_method == "direct_raw":
                await self._call(
                    DeleteArtifact(project_id=project_id, path=str(transferred.path)),
                    response_type=TransferAcknowledgement,
                )
            else:
                await self._cancel_stage(project_id, str(transferred.stage_id))
        except Exception as exc:
            return str(exc)
        return ""

    async def import_workspace_file(
        self,
        project_id: str,
        workspace_path: str,
        project_folder: str = "/",
        language: str = "",
        compiler_spec: str = "",
        auto_analyze: bool = True,
    ) -> WorkspaceImportReceipt:
        transferred = await self._transfer_workspace_file(project_id, workspace_path)
        try:
            result = await self._call(
                ImportBinary(
                    project_id=project_id,
                    file_path=transferred.path,
                    project_folder=project_folder,
                    language=language,
                    compiler_spec=compiler_spec,
                    auto_analyze=auto_analyze,
                ),
                response_type=ImportedBinaryReply,
            )
        except Exception:
            await self._cleanup_transfer_best_effort(project_id, transferred)
            raise
        cleanup_error = await self._cleanup_transfer_best_effort(project_id, transferred)
        return WorkspaceImportReceipt(
            workspace_path=workspace_path,
            sha256=transferred.sha256,
            transfer_method=transferred.transfer_method,
            direct_upload_error=transferred.direct_upload_error,
            result=result.receipt,
            transfer_cleanup_error=cleanup_error,
        )

    async def import_workspace_program(
        self,
        project_id: str,
        workspace_path: str,
        target_folder: str = "/",
        target_name: str = "",
        overwrite: bool = False,
    ) -> WorkspaceImportReceipt:
        transferred = await self._transfer_workspace_file(project_id, workspace_path)
        try:
            result = await self._call(
                ImportProgram(
                    project_id=project_id,
                    gzf_path=transferred.path,
                    target_folder=target_folder,
                    target_name=target_name,
                    overwrite=overwrite,
                ),
                response_type=ImportedProgramReply,
            )
        except Exception:
            await self._cleanup_transfer_best_effort(project_id, transferred)
            raise
        cleanup_error = await self._cleanup_transfer_best_effort(project_id, transferred)
        return WorkspaceImportReceipt(
            workspace_path=workspace_path,
            sha256=transferred.sha256,
            transfer_method=transferred.transfer_method,
            direct_upload_error=transferred.direct_upload_error,
            result=result.receipt,
            transfer_cleanup_error=cleanup_error,
        )

    async def restore_workspace_project(
        self,
        project_id: str,
        workspace_path: str,
        project_name: str,
        parent_dir: str = "",
    ) -> WorkspaceImportReceipt:
        transferred = await self._transfer_workspace_file(project_id, workspace_path)
        try:
            result = await self._call(
                RestoreProject(
                    project_id=project_id,
                    gar_path=transferred.path,
                    project_name=project_name,
                    parent_dir=parent_dir,
                ),
                response_type=RestoredProjectReply,
            )
        except Exception:
            await self._cleanup_transfer_best_effort(project_id, transferred)
            raise
        cleanup_error = await self._cleanup_transfer_best_effort(project_id, transferred)
        return WorkspaceImportReceipt(
            workspace_path=workspace_path,
            sha256=transferred.sha256,
            transfer_method=transferred.transfer_method,
            direct_upload_error=transferred.direct_upload_error,
            result=result.receipt,
            transfer_cleanup_error=cleanup_error,
        )

    def _artifact_data(self, chunk: ArtifactChunk, offset: int) -> bytes:
        try:
            data = base64.b64decode(chunk.data_base64, validate=True)
            chunk.progress.require_chunk(offset, len(data), self.max_file_bytes)
        except (ValueError, binascii.Error) as exc:
            raise AnalysisTransferError(str(exc)) from exc
        return data

    async def _copy_artifact_to_workspace(
        self,
        project_id: str,
        artifact_path: str,
        workspace_path: str,
        *,
        overwrite: bool,
    ) -> WorkspaceArtifactExport:
        target = self._workspace.target_path(workspace_path)
        if target.exists() and not overwrite:
            raise AnalysisTransferError(f"workspace destination already exists: {workspace_path}")
        if target.exists() and target.is_dir():
            raise AnalysisTransferError("workspace destination is a directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / (f".{target.name}.analysis-transfer-{uuid.uuid4().hex}.part")
        temporary.unlink(missing_ok=True)

        offset = 0
        size_bytes = 0
        try:
            with temporary.open("xb") as handle:
                while True:
                    chunk = await self._call(
                        ReadArtifact(
                            project_id=project_id,
                            path=artifact_path,
                            offset=offset,
                            length=self.chunk_bytes,
                        ),
                        response_type=ArtifactChunk,
                    )
                    data = self._artifact_data(chunk, offset)
                    handle.write(data)
                    offset = chunk.next_offset
                    size_bytes = chunk.size_bytes
                    if chunk.eof is True:
                        break
                handle.flush()
            if offset != size_bytes:
                raise AnalysisTransferError("analysis artifact transfer ended at unexpected size")
            if target.exists():
                target.unlink()
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

        info = self._workspace.file_info(workspace_path)
        if info is None:
            raise AnalysisTransferError("workspace destination is not a file")
        digest = self._workspace.sha256(workspace_path)
        cleanup_error = ""
        try:
            await self._call(
                DeleteArtifact(project_id=project_id, path=artifact_path),
                response_type=TransferAcknowledgement,
            )
            source_deleted = True
        except Exception as exc:
            cleanup_error = str(exc)
            source_deleted = False
        return WorkspaceArtifactExport(
            path=info.path,
            name=info.name,
            size_bytes=info.size_bytes,
            modified_at_ns=info.modified_at_ns,
            mime_type=info.mime_type,
            type=info.type,
            sha256=digest,
            source_artifact_path=artifact_path,
            source_deleted=source_deleted,
            source_cleanup_error=cleanup_error,
        )

    async def export_program_to_workspace(
        self,
        project_id: str,
        program_name: str,
        workspace_path: str,
        *,
        overwrite: bool = False,
    ) -> WorkspaceArtifactExport:
        output_name = f"{uuid.uuid4().hex}-{Path(workspace_path).name}"
        exported = await self._call(
            ExportProgram(
                project_id=project_id,
                program_name=program_name,
                output_dir="/artifacts/exports",
                output_name=output_name,
            ),
            response_type=ArtifactExportPath,
        )
        artifact_path = exported.path
        return await self._copy_artifact_to_workspace(
            project_id,
            artifact_path,
            workspace_path,
            overwrite=overwrite,
        )

    async def archive_project_to_workspace(
        self,
        project_id: str,
        workspace_path: str,
        *,
        overwrite: bool = False,
    ) -> WorkspaceArtifactExport:
        output_name = f"{uuid.uuid4().hex}-{Path(workspace_path).name}"
        archived = await self._call(
            ArchiveProject(
                project_id=project_id, output_dir="/artifacts/exports", output_name=output_name
            ),
            response_type=ArtifactExportPath,
        )
        artifact_path = archived.path
        return await self._copy_artifact_to_workspace(
            project_id,
            artifact_path,
            workspace_path,
            overwrite=overwrite,
        )


class _OwnerWorkspaceAdapter(_WorkspaceBinding[WorkspaceFileStore]):
    def path_for(self, relative: str) -> Path:
        return self._workspace.path_for(relative)

    def target_path(self, relative: str) -> Path:
        return self._workspace.target_path(relative)

    def sha256(self, relative: str) -> str:
        return self._workspace.sha256(relative)

    def file_info(self, relative: str) -> WorkspaceFileMetadata | None:
        entry = self._workspace.info(relative)
        if not isinstance(entry, WorkspaceFileEntry):
            return None
        return WorkspaceFileMetadata(
            path=entry.path,
            name=entry.name,
            size_bytes=entry.size_bytes,
            modified_at_ns=entry.modified_at_ns,
            mime_type=entry.mime_type,
            type=entry.type,
        )


class _CompositionAnalysisWorkspaceTransfers[
    SettingsT: AnalysisBackendConfiguration,
    WorkspaceT: WorkspaceFileStore,
](AnalysisWorkspaceTransfers):
    _workspace_adapter_type: Callable[[WorkspaceT], AnalysisWorkspacePort]

    def __init__(
        self,
        settings: SettingsT,
        workspace: WorkspaceT,
        *,
        max_file_bytes: int,
        chunk_bytes: int = 1024 * 1024,
    ) -> None:
        self._owner_workspace = workspace
        super().__init__(
            settings,
            self._workspace_adapter_type(workspace),
            max_file_bytes=max_file_bytes,
            chunk_bytes=chunk_bytes,
        )

    @property
    def workspace(self) -> WorkspaceT:
        return self._owner_workspace

    @workspace.setter
    def workspace(self, workspace: WorkspaceT) -> None:
        self._owner_workspace = workspace
        self._workspace = self._workspace_adapter_type(workspace)
