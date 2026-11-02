"""The exact direct-upload and committed-stage receipts exposed by Analysis."""

from typing import Literal

from pydantic import StrictInt

from modules.analysis.domain.artifacts import ArtifactContent
from modules.analysis.transfer_views import DirectArtifactReceipt, StageFinished


class ProjectArtifactReceipt(StageFinished):
    """All committed-stage metadata from the pinned provider."""


class ProjectArtifactTransfer(DirectArtifactReceipt):
    workspace_path: str

    @classmethod
    def received(
        cls,
        receipt: DirectArtifactReceipt,
        workspace_path: str,
        project_id: str,
        expected: ArtifactContent,
    ) -> "ProjectArtifactTransfer":
        expected.require_match(receipt.content)
        if not receipt.success or receipt.project_id != project_id:
            raise ValueError("Verified artifact receipt for this project required")
        return cls(
            success=receipt.success,
            project_id=receipt.project_id,
            path=receipt.path,
            size_bytes=receipt.size_bytes,
            sha256=receipt.sha256,
            transfer_method=receipt.transfer_method,
            workspace_path=workspace_path,
        )


class StagedProjectArtifactTransfer(ProjectArtifactReceipt):
    workspace_path: str
    size_bytes: StrictInt
    transfer_method: Literal["mcp_base64"]

    @classmethod
    def received(
        cls,
        receipt: ProjectArtifactReceipt,
        workspace_path: str,
        expected: ArtifactContent,
    ) -> "StagedProjectArtifactTransfer":
        expected.require_match(receipt.content)
        return cls(
            stage_id=receipt.stage_id,
            name=receipt.name,
            expected_size=receipt.expected_size,
            bytes_received=receipt.bytes_received,
            next_offset=receipt.next_offset,
            remaining_bytes=receipt.remaining_bytes,
            complete=receipt.complete,
            committed=receipt.committed,
            chunk_bytes=receipt.chunk_bytes,
            path=receipt.path,
            sha256=receipt.sha256,
            workspace_path=workspace_path,
            size_bytes=expected.size_bytes,
            transfer_method="mcp_base64",
        )
