"""Project-volume bytes to private Ghidra via fixed loopback; staged fallback."""

import asyncio
import base64
import os
from collections.abc import AsyncIterator
from contextlib import suppress

import httpx
from fastmcp import FastMCP
from pydantic import BaseModel

from hand_runtime.runtime_policy import runtime_policy
from modules.analysis.domain.artifacts import ArtifactContent
from modules.analysis.infrastructure.artifact_client import call_artifact
from modules.analysis.infrastructure.artifact_commands import (
    ArtifactCommand,
    BeginArtifact,
    CancelArtifact,
    FinishArtifact,
    WriteArtifact,
)
from modules.analysis.provider import AnalysisToolProvider
from modules.analysis.transfer_views import (
    DirectArtifactReceipt,
    StageOpened,
    StageWritten,
    TransferAcknowledgement,
)

from .domain.project_source import MAX_TRANSFER_BYTES
from .infrastructure.project_source import source_snapshot as source_snapshot
from .transfer_views import (
    ProjectArtifactReceipt,
    ProjectArtifactTransfer,
    StagedProjectArtifactTransfer,
)


class UnsupportedUpload(Exception):
    """Explicit older-engine endpoint absence permits staged fallback."""


MAX_BYTES = MAX_TRANSFER_BYTES


async def _call[T: BaseModel](
    provider: AnalysisToolProvider, command: ArtifactCommand, response_type: type[T]
) -> T:
    return await call_artifact(provider._backend_pool, command, response_type)


def register_transfer[AppState](mcp: FastMCP[AppState], provider: AnalysisToolProvider) -> None:
    @mcp.tool()
    async def upload_project_file(
        project_id: str, workspace_path: str
    ) -> ProjectArtifactTransfer | StagedProjectArtifactTransfer:
        """Copy a file from this placement's read-only shared project workspace into Analysis.

        Call via analysis_start(engine="ghidra",tool="upload_project_file",arguments=...).
        Returns artifact path for the normal import tool. Direct raw bytes use
        private loopback; older engines use staged chunks. No host paths/URLs.
        """
        if os.environ.get("BRIAREUS_PROJECT_TRANSFER") != "1":
            raise ValueError("Attach this project's workspace first")
        with source_snapshot(workspace_path) as (source, size, digest):

            async def chunks() -> AsyncIterator[bytes]:
                with source.open("rb") as stream:
                    while block := stream.read(1024**2):
                        yield block
                        await asyncio.sleep(0)

            try:
                async with httpx.AsyncClient(
                    timeout=runtime_policy().execution_timeout_seconds,
                    trust_env=False,
                    follow_redirects=False,
                ) as client:
                    reply = await client.post(
                        "http://127.0.0.1:8081/internal/artifacts/upload",
                        params={"project_id": project_id, "name": source.name},
                        headers={
                            "X-Koba-Proxy-Origin": "analysis",
                            "X-Artifact-Size": str(size),
                            "X-Artifact-SHA256": digest,
                            "Content-Type": "application/octet-stream",
                        },
                        content=chunks(),
                    )
                if reply.status_code in {404, 405, 501}:
                    raise UnsupportedUpload
                reply.raise_for_status()
                receipt = DirectArtifactReceipt.model_validate_json(reply.content)
                return ProjectArtifactTransfer.received(
                    receipt, workspace_path, project_id, ArtifactContent(size, digest)
                )
            except UnsupportedUpload:
                pass
            begun = await _call(
                provider,
                BeginArtifact(
                    project_id=project_id, name=source.name, size_bytes=size, sha256=digest
                ),
                StageOpened,
            )
            stage = begun.stage_id
            try:
                offset = 0
                with source.open("rb") as stream:
                    while block := stream.read(24000):
                        written = await _call(
                            provider,
                            WriteArtifact(
                                project_id=project_id,
                                stage_id=stage,
                                offset=offset,
                                data_base64=base64.b64encode(block).decode(),
                            ),
                            StageWritten,
                        )
                        if written.next_offset != offset + len(block):
                            raise ValueError("Invalid stage offset")
                        offset += len(block)
                result = await _call(
                    provider,
                    FinishArtifact(project_id=project_id, stage_id=stage),
                    ProjectArtifactReceipt,
                )
                return StagedProjectArtifactTransfer.received(
                    result, workspace_path, ArtifactContent(size, digest)
                )
            except BaseException:
                with suppress(Exception):
                    await _call(
                        provider,
                        CancelArtifact(project_id=project_id, stage_id=stage),
                        TransferAcknowledgement,
                    )
                raise
