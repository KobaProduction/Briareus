"""Verified artifact content and receipts owned by the Analysis workspace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ArtifactContent:
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        if self.size_bytes < 0:
            raise ValueError("Artifact size must be non-negative")
        if len(self.sha256) != 64 or any(char not in "0123456789abcdef" for char in self.sha256):
            raise ValueError("Artifact SHA-256 must be a lowercase hexadecimal digest")

    def require_match(self, received: ArtifactContent) -> None:
        if self != received:
            raise ValueError("Artifact receipt does not match the transferred content")


@dataclass(frozen=True, slots=True)
class ArtifactChunkProgress:
    offset: int
    next_offset: int
    size_bytes: int
    bytes_read: int
    eof: bool

    def require_chunk(self, expected_offset: int, actual_bytes: int, max_file_bytes: int) -> None:
        if self.size_bytes > max_file_bytes:
            raise ValueError("Analysis artifact exceeds configured size limit")
        if self.offset != expected_offset or self.bytes_read != actual_bytes:
            raise ValueError("Analysis artifact read returned inconsistent chunk metadata")
        if self.next_offset != expected_offset + actual_bytes or self.next_offset > self.size_bytes:
            raise ValueError("Analysis artifact read returned invalid offset")
        if self.eof != (self.next_offset == self.size_bytes) or (
            not self.eof and actual_bytes == 0
        ):
            raise ValueError("Analysis artifact read did not reach a valid continuation")


@dataclass(frozen=True, slots=True)
class StagedWorkspaceArtifact:
    path: str
    workspace_path: str
    size_bytes: int
    sha256: str
    transfer_method: Literal["direct_raw", "mcp_base64"]
    stage_id: str = ""
    direct_upload_error: str = ""

    def __post_init__(self) -> None:
        ArtifactContent(self.size_bytes, self.sha256)
        if not self.path:
            raise ValueError("Artifact path required")
        if self.transfer_method == "mcp_base64" and not self.stage_id:
            raise ValueError("Staged artifact requires its provider stage identifier")


@dataclass(frozen=True, slots=True)
class ImportedBinary:
    success: bool
    name: str
    path: str
    language: str
    analyzing: bool
    auto_analyzed: bool


@dataclass(frozen=True, slots=True)
class ImportedProgram:
    success: bool
    project: str
    folder: str
    program: str
    content_type: str


@dataclass(frozen=True, slots=True)
class RestoredProject:
    success: bool
    project: str
    project_path: str
    project_storage_dir: str


@dataclass(frozen=True, slots=True)
class WorkspaceImportReceipt:
    workspace_path: str
    sha256: str
    transfer_method: Literal["direct_raw", "mcp_base64"]
    direct_upload_error: str
    result: ImportedBinary | ImportedProgram | RestoredProject
    transfer_cleanup_error: str


@dataclass(frozen=True, slots=True)
class WorkspaceArtifactExport:
    path: str
    name: str
    size_bytes: int
    modified_at_ns: int
    mime_type: str
    type: Literal["file"]
    sha256: str
    source_artifact_path: str
    source_deleted: bool
    source_cleanup_error: str
