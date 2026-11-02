"""Requests for the pinned Ghidra artifact API; provider IDs remain provider strings."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class ArtifactCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tool_name: ClassVar[str]
    project_id: str


class BeginArtifact(ArtifactCommand):
    tool_name = "artifact_stage_begin"
    name: str
    size_bytes: int = Field(ge=0)
    sha256: str


class WriteArtifact(ArtifactCommand):
    tool_name = "artifact_stage_write"
    stage_id: str
    offset: int = Field(ge=0)
    data_base64: str


class FinishArtifact(ArtifactCommand):
    tool_name = "artifact_stage_finish"
    stage_id: str


class CancelArtifact(FinishArtifact):
    tool_name = "artifact_stage_cancel"


class DeleteArtifact(ArtifactCommand):
    tool_name = "artifact_file_delete"
    path: str


class ReadArtifact(DeleteArtifact):
    tool_name = "artifact_file_read"
    offset: int = Field(ge=0)
    length: int = Field(gt=0)


class ImportBinary(ArtifactCommand):
    tool_name = "import_file"
    file_path: str
    project_folder: str
    language: str
    compiler_spec: str
    auto_analyze: bool


class ImportProgram(ArtifactCommand):
    tool_name = "import_program"
    gzf_path: str
    target_folder: str
    target_name: str
    overwrite: bool


class RestoreProject(ArtifactCommand):
    tool_name = "restore_project"
    gar_path: str
    project_name: str
    parent_dir: str


class ArchiveProject(ArtifactCommand):
    tool_name = "archive_project"
    output_dir: str
    output_name: str


class ExportProgram(ArchiveProject):
    tool_name = "export_program"
    program_name: str
