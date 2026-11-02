"""Concrete replies from the pinned Ghidra staging and import endpoints."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from project_runtime_client.analysis.domain.artifacts import (
    ArtifactChunkProgress,
    ArtifactContent,
    ImportedBinary,
    ImportedProgram,
    RestoredProject,
)


class ArtifactReply(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)


class ArtifactStageStatus(ArtifactReply):
    stage_id: str = Field(min_length=1)
    name: str
    expected_size: StrictInt = Field(ge=0)
    bytes_received: StrictInt = Field(ge=0)
    next_offset: StrictInt = Field(ge=0)
    remaining_bytes: StrictInt = Field(ge=0)
    complete: StrictBool
    committed: StrictBool
    chunk_bytes: StrictInt = Field(gt=0)


class StageOpened(ArtifactStageStatus):
    """The initial stage status returned by artifact_stage_begin."""


class StageWritten(ArtifactStageStatus):
    """The updated stage status returned by artifact_stage_write."""


class StageFinished(ArtifactStageStatus):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def content(self) -> ArtifactContent:
        return ArtifactContent(self.bytes_received, self.sha256)


class DirectArtifactReceipt(ArtifactReply):
    success: StrictBool
    project_id: str
    path: str = Field(min_length=1)
    size_bytes: StrictInt = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transfer_method: Literal["direct_raw"]

    @property
    def content(self) -> ArtifactContent:
        return ArtifactContent(self.size_bytes, self.sha256)


class ArtifactChunk(ArtifactReply):
    path: str
    offset: StrictInt = Field(ge=0)
    bytes_read: StrictInt = Field(ge=0)
    data_base64: str
    next_offset: StrictInt = Field(ge=0)
    size_bytes: StrictInt = Field(ge=0)
    eof: StrictBool

    @property
    def progress(self) -> ArtifactChunkProgress:
        return ArtifactChunkProgress(
            self.offset, self.next_offset, self.size_bytes, self.bytes_read, self.eof
        )


class ArtifactExportPath(ArtifactReply):
    success: StrictBool
    path: str = Field(min_length=1)
    size_bytes: StrictInt = Field(ge=0)
    content_type: str
    program: str | None = None
    project: str | None = None


class TransferAcknowledgement(ArtifactReply):
    """Only success/failure is consumed; provider cleanup details stay private."""


class ImportedBinaryReply(ArtifactReply):
    success: StrictBool
    name: str
    path: str
    language: str
    analyzing: StrictBool
    auto_analyzed: StrictBool

    @property
    def receipt(self) -> ImportedBinary:
        return ImportedBinary(
            self.success, self.name, self.path, self.language, self.analyzing, self.auto_analyzed
        )


class ImportedProgramReply(ArtifactReply):
    success: StrictBool
    project: str
    folder: str
    program: str
    content_type: str

    @property
    def receipt(self) -> ImportedProgram:
        return ImportedProgram(
            self.success, self.project, self.folder, self.program, self.content_type
        )


class RestoredProjectReply(ArtifactReply):
    success: StrictBool
    project: str
    project_path: str
    project_storage_dir: str

    @property
    def receipt(self) -> RestoredProject:
        return RestoredProject(
            self.success, self.project, self.project_path, self.project_storage_dir
        )
